"""Cliente MQTT de terminal para Hearmony, com histórico JSON local."""

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt
from dotenv import load_dotenv
from anc_simulation import simular_anc


PASTA = Path(__file__).resolve().parent
HISTORY_FILE = PASTA / "historico.json"
HISTORY_LIMIT = 1000
TIMEOUT = 5
DADOS_LOCK = threading.Lock()
CONECTADO = threading.Event()
NOVA_TELEMETRIA = threading.Event()
ULTIMA_TELEMETRIA = None

load_dotenv(PASTA / ".env")
MQTT_HOST = os.environ.get(
    "MQTT_HOST", "h6ee1016.ala.us-east-1.emqxsl.com"
).strip()
MQTT_PORT = int(os.environ.get("MQTT_PORT", "8883"))
MQTT_USERNAME = os.environ.get("MQTT_USERNAME", "").strip()
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "")
MQTT_CLIENT_ID = os.environ.get("MQTT_CLIENT_ID", "hearmony-python-client")
MQTT_TELEMETRY_TOPIC = os.environ.get(
    "MQTT_TELEMETRY_TOPIC", "hearmony/device/+/telemetry"
)
MQTT_COMMAND_TOPIC = os.environ.get(
    "MQTT_COMMAND_TOPIC", "hearmony/device/hearmony-01/commands"
)
CLIENTE_MQTT = None


# Lê e grava o histórico recebido pelo cliente.
def carregar_historico():
    try:
        with HISTORY_FILE.open("r", encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
        return dados if isinstance(dados, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def salvar_historico(registros):
    temporario = HISTORY_FILE.with_suffix(".tmp")
    temporario.write_text(
        json.dumps(registros[-HISTORY_LIMIT:], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporario.replace(HISTORY_FILE)


# Callbacks chamados pela biblioteca ao conectar e receber mensagens.
def ao_conectar(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        CONECTADO.set()
        resultado, _ = client.subscribe(MQTT_TELEMETRY_TOPIC, qos=1)
        if resultado == mqtt.MQTT_ERR_SUCCESS:
            print("Conectado ao broker; assinatura de telemetria ativa.")
        else:
            print(
                "Conectou ao broker, mas não conseguiu assinar "
                "o tópico de telemetria."
            )
    else:
        print("Conexão MQTT recusada:", reason_code)


def ao_desconectar(client, userdata, disconnect_flags, reason_code, properties):
    CONECTADO.clear()
    if reason_code != 0:
        print("Conexão MQTT interrompida; o cliente tentará reconectar.")


def ao_receber_mensagem(client, userdata, mensagem):
    global ULTIMA_TELEMETRIA
    try:
        telemetria = json.loads(mensagem.payload.decode("utf-8"))
        if not isinstance(telemetria, dict):
            return
    except (UnicodeDecodeError, json.JSONDecodeError):
        print("Mensagem MQTT ignorada: JSON inválido.")
        return

    registro = {
        "telemetria": telemetria,
        "resultado_python": "recebida via MQTT",
        "recebida_em": datetime.now(timezone.utc).isoformat(),
    }
    with DADOS_LOCK:
        ULTIMA_TELEMETRIA = telemetria
        historico = carregar_historico()
        historico.append(registro)
        salvar_historico(historico)
    NOVA_TELEMETRIA.set()


def iniciar_mqtt():
    global CLIENTE_MQTT
    if not MQTT_USERNAME or not MQTT_PASSWORD:
        print("Configure MQTT_USERNAME e MQTT_PASSWORD no arquivo python/.env.")
        return

    CLIENTE_MQTT = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=MQTT_CLIENT_ID,
        protocol=mqtt.MQTTv311,
    )
    CLIENTE_MQTT.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    CLIENTE_MQTT.tls_set()
    CLIENTE_MQTT.on_connect = ao_conectar
    CLIENTE_MQTT.on_disconnect = ao_desconectar
    CLIENTE_MQTT.on_message = ao_receber_mensagem

    try:
        CLIENTE_MQTT.connect_async(MQTT_HOST, MQTT_PORT, keepalive=60)
        CLIENTE_MQTT.loop_start()
        CONECTADO.wait(TIMEOUT)
        if not CONECTADO.is_set():
            print("Ainda não foi possível conectar ao broker MQTT.")
    except (OSError, ValueError) as erro:
        print("Falha ao iniciar conexão MQTT:", erro)


def obter_ultima_telemetria(esperar=False):
    if esperar and ULTIMA_TELEMETRIA is None and CONECTADO.is_set():
        NOVA_TELEMETRIA.wait(TIMEOUT)
    with DADOS_LOCK:
        return ULTIMA_TELEMETRIA


def verificar_conexao():
    if CLIENTE_MQTT is None or not CONECTADO.is_set():
        print("Broker MQTT desconectado. Confira python/.env e a rede.")
        return None
    telemetria = obter_ultima_telemetria(esperar=True)
    if telemetria is None:
        print("Broker conectado; ainda não chegou telemetria do ESP32.")
        return None
    print("Telemetria mais recente:", telemetria)
    return telemetria


def opcao_conexao_e_simulacao():
    telemetria = verificar_conexao()
    if telemetria is None:
        return

    if telemetria.get("anc_simulado"):
        resultado = simular_anc(telemetria)
    else:
        resultado = "proteção simulada inativa"
    print("Resultado da simulação:", resultado)


def opcao_consultar():
    verificar_conexao()


def validar_limite(valor):
    try:
        limite = int(valor)
    except ValueError:
        raise ValueError("Digite um número inteiro entre 55 e 85.") from None
    if limite < 55:
        raise ValueError("O limite mínimo é 55.")
    elif limite > 85:
        raise ValueError("O limite máximo é 85.")
    else:
        return limite


# Publica no broker o novo limite escolhido no menu.
def opcao_enviar_comando():
    if CLIENTE_MQTT is None or not CONECTADO.is_set():
        print("Broker MQTT desconectado. Não foi possível enviar o limite.")
        return
    try:
        limite = validar_limite(input("Novo limite (55 a 85): "))
        payload = json.dumps({"threshold": limite})
        resultado = CLIENTE_MQTT.publish(
            MQTT_COMMAND_TOPIC,
            payload,
            qos=1,
            retain=False,
        )
        if resultado.rc != mqtt.MQTT_ERR_SUCCESS:
            print("Falha ao publicar o comando MQTT.")
            return
        resultado.wait_for_publish(timeout=TIMEOUT)
        if resultado.is_published():
            print(
                "Limite publicado. O ESP32 aplica o comando ao receber "
                "a próxima mensagem."
            )
        else:
            print("O broker não confirmou a publicação dentro do tempo limite.")
    except ValueError as erro:
        print("Entrada inválida:", erro)


def opcao_historico():
    with DADOS_LOCK:
        registros = carregar_historico()
    if not registros:
        print("Ainda não há telemetrias salvas neste computador.")
        return
    inicio = max(1, len(registros) - 19)
    for indice, registro in enumerate(registros[-20:], start=inicio):
        telemetria = registro.get("telemetria", {})
        print(
            indice,
            "| horário:", registro.get("recebida_em", "desconhecido"),
            "| ruído:", telemetria.get("noise"),
            "| ANC:", telemetria.get("anc_simulado"),
            "| estado:", telemetria.get("state"),
        )
    print("Histórico completo:", HISTORY_FILE)


def opcao_status():
    print("Broker:", MQTT_HOST + ":" + str(MQTT_PORT))
    print("Estado:", "conectado" if CONECTADO.is_set() else "desconectado")
    print("Tópico de telemetria:", MQTT_TELEMETRY_TOPIC)
    print("Tópico de comandos:", MQTT_COMMAND_TOPIC)


def menu():
    iniciar_mqtt()
    opcoes = (
        "Verificar conexão e simular ANC",
        "Consultar telemetria mais recente",
        "Enviar limite ao ESP32",
        "Ver histórico local",
        "Ver configuração MQTT",
        "Sair",
    )
    try:
        while True:
            print("\n=== Hearmony | Cliente MQTT Python ===")
            for numero, opcao in enumerate(opcoes):
                print(str(numero) + " - " + opcao)
            escolha = input("Escolha: ").strip()
            match escolha:
                case "0":
                    opcao_conexao_e_simulacao()
                case "1":
                    opcao_consultar()
                case "2":
                    opcao_enviar_comando()
                case "3":
                    opcao_historico()
                case "4":
                    opcao_status()
                case "5":
                    print("Até logo!")
                    break
                case _:
                    print("Opção inválida. Escolha um número entre 0 e 5.")
    finally:
        if CLIENTE_MQTT is not None:
            CLIENTE_MQTT.loop_stop()
            CLIENTE_MQTT.disconnect()


if __name__ == "__main__":
    try:
        menu()
    except (KeyboardInterrupt, EOFError):
        print("\nPrograma encerrado.")




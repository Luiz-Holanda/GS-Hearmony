"""Dashboard web local para acompanhar o protótipo Edge Hearmony."""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Permite reutilizar as configurações, callbacks MQTT e histórico do cliente Python.
RAIZ_PROJETO = Path(__file__).resolve().parent.parent
PASTA_PYTHON = RAIZ_PROJETO / "python"
sys.path.insert(0, str(PASTA_PYTHON))
import client


PASTA = Path(__file__).resolve().parent
ARQUIVO_HTML = PASTA / "dashboard.html"
# Servidor restrito ao próprio computador; não expõe o painel na rede local.
HOST = "127.0.0.1"
PORTA = 8080


def obter_historico_recente():
    """Carrega os últimos registros salvos pelo cliente MQTT."""
    try:
        with client.HISTORY_FILE.open("r", encoding="utf-8") as arquivo:
            registros = json.load(arquivo)
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(registros, list):
        return []

    recentes = []
    for registro in registros[-12:]:
        if not isinstance(registro, dict):
            continue
        telemetria = registro.get("telemetria", {})
        if isinstance(telemetria, dict):
            recentes.append({
                "noise": telemetria.get("noise"),
                "state": telemetria.get("state", "desconhecido"),
                "received_at": registro.get("recebida_em")
                or telemetria.get("received_at"),
            })
    return recentes


class DashboardHandler(BaseHTTPRequestHandler):
    """Entrega a página e a API local usada pelo navegador."""

    def enviar_json(self, status, dados):
        """Envia uma resposta JSON com cabeçalhos adequados para a API."""
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        # A API fornece o estado MQTT e o histórico atualizado para a página.
        if self.path == "/api/status":
            with client.DADOS_LOCK:
                telemetria = client.ULTIMA_TELEMETRIA
            self.enviar_json(200, {
                "connected": client.CONECTADO.is_set(),
                "telemetry": telemetria,
                "history": obter_historico_recente(),
            })
            return

        if self.path not in ("/", "/dashboard.html"):
            self.enviar_json(404, {"error": "Página não encontrada."})
            return

        try:
            corpo = ARQUIVO_HTML.read_bytes()
        except OSError:
            self.enviar_json(500, {"error": "Não foi possível abrir o dashboard."})
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def do_POST(self):
        # Valida o novo limite recebido da interface antes de publicá-lo.
        if self.path != "/api/threshold":
            self.enviar_json(404, {"error": "Rota não encontrada."})
            return

        try:
            tamanho = int(self.headers.get("Content-Length", "0"))
            if tamanho < 1 or tamanho > 1024:
                raise ValueError
            dados = json.loads(self.rfile.read(tamanho).decode("utf-8"))
            limite = dados.get("threshold")
            if not isinstance(limite, int) or isinstance(limite, bool):
                raise ValueError
            limite = client.validar_limite(str(limite))
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, ValueError):
            self.enviar_json(400, {"error": "Informe um limite inteiro entre 55 e 85."})
            return

        if client.CLIENTE_MQTT is None or not client.CONECTADO.is_set():
            self.enviar_json(503, {"error": "Broker MQTT desconectado."})
            return

        payload = json.dumps({"threshold": limite})
        resultado = client.CLIENTE_MQTT.publish(
            client.MQTT_COMMAND_TOPIC, payload, qos=1, retain=False
        )
        if resultado.rc != client.mqtt.MQTT_ERR_SUCCESS:
            self.enviar_json(502, {"error": "Não foi possível publicar o limite."})
            return

        try:
            resultado.wait_for_publish(timeout=client.TIMEOUT)
            if not resultado.is_published():
                self.enviar_json(504, {"error": "O broker não confirmou o envio."})
                return
        except RuntimeError:
            self.enviar_json(502, {"error": "Falha ao confirmar o envio MQTT."})
            return

        self.enviar_json(200, {"message": "Limite enviado ao ESP32.", "threshold": limite})

    def log_message(self, formato, *args):
        print("Dashboard:", formato % args)


def main():
    """Inicia MQTT e mantém o servidor web local em execução."""
    client.iniciar_mqtt()
    servidor = ThreadingHTTPServer((HOST, PORTA), DashboardHandler)
    print("Hearmony Edge Dashboard: http://%s:%d" % (HOST, PORTA))
    print("Use Ctrl+C para encerrar.")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando dashboard...")
    finally:
        servidor.server_close()
        if client.CLIENTE_MQTT is not None:
            client.CLIENTE_MQTT.loop_stop()
            client.CLIENTE_MQTT.disconnect()


if __name__ == "__main__":
    main()

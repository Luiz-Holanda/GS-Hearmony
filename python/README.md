# 🐍 Hearmony — Aplicação Python

## 📌 Sobre o módulo

O Hearmony propõe uma tecnologia assistiva para pessoas que sentem desconforto com sons intensos ou imprevisíveis. A intenção é oferecer mais autonomia para lidar com esses estímulos e buscar equilíbrio entre conforto e percepção de sons importantes para a segurança.

Este módulo Python se relaciona com essa proposta ao permitir acompanhar as leituras do ESP32, enviar um limite de resposta e consultar o histórico recebido. Com esses recursos, o grupo consegue observar como diferentes valores da escala simulada afetam os estados do protótipo.

O Python não recebe uma medição acústica real: o valor `noise` vem do potenciômetro usado no Wokwi, que representa de 0 a 100 pontos.

---

## 🎯 Objetivos

* Acompanhar a telemetria publicada pelo ESP32;
* Exibir o estado mais recente do protótipo;
* Enviar um limite personalizado ao dispositivo;
* Registrar e consultar o histórico local;
* Demonstrar como a aplicação se integra ao módulo Edge pelo broker MQTT.

---

## 🔄 Relação com os outros módulos

O ESP32 toma a decisão imediata e sinaliza o estado localmente. O EMQX Cloud encaminha os dados e comandos; este cliente Python recebe as leituras, publica limites e mantém um histórico neste computador. A interface Web integra a solução global em outro módulo do projeto.

```text
ESP32 → telemetria → EMQX Cloud → Python → histórico local
ESP32 ← novo limite ← EMQX Cloud ← Python
```

O cliente precisa estar aberto para registrar cada mensagem recebida. Se estiver fechado, o broker mantém apenas a leitura mais recente retida; as mensagens intermediárias não são recuperadas.

---

## 🚀 Como executar

Use Python 3.10 ou superior. Copie `.env.example` para `.env` e informe `MQTT_USERNAME` e `MQTT_PASSWORD` do usuário MQTT do Python. Não use o App ID ou App Secret de gerenciamento do EMQX.

Na pasta principal do projeto, instale as dependências e inicie o menu:

```powershell
py -3 -m pip install -r python\requirements.txt
py -3 python\client.py
```

O arquivo `.env` local é ignorado pelo Git. Não compartilhe as credenciais MQTT.

---

## 🧭 Opções do menu

* Verificar a conexão e iniciar a simulação matemática;
* Consultar a telemetria mais recente;
* Enviar um limite entre 55 e 85 pontos;
* Consultar as últimas leituras do histórico;
* Conferir host, tópicos e estado da conexão.

O histórico fica em `historico.json` e guarda até 1.000 registros. A simulação FxLMS é um modelo matemático demonstrativo; não processa áudio real e não realiza cancelamento físico de ruído. O escopo do Hearmony não inclui desenvolver um ANC próprio.

---

## 📡 Comunicação MQTT

| Informação | Configuração |
|---|---|
| Broker | `h6ee1016.ala.us-east-1.emqxsl.com` |
| Porta | `8883` — MQTT com TLS |
| Telemetria | `hearmony/device/+/telemetry` — assinatura |
| Comandos | `hearmony/device/hearmony-01/commands` — publicação |

O usuário MQTT do Python precisa de permissão para assinar o tópico de telemetria e publicar no tópico de comandos.

---

## 🔗 Projeto e apresentação

* [Projeto Wokwi](https://wokwi.com/projects/479326589809502209)
* [Vídeo de apresentação no YouTube](https://youtu.be/YAFtddJl21g)

---

# 👥 Equipe

* Luiz Alberto De Carvalho Holanda Junior
* Felipe Ribeiro Da Silva
* Milena Kubo de Biaggi
* Yasmim Eun Hae Kim

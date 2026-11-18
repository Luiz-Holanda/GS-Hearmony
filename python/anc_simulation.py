"""Simulação didática de ANC feedforward de um tom usando FxLMS simplificado."""

import math


# Calcula o valor RMS de uma lista de amostras.
def calcular_rms(amostras):
    if not amostras:
        return 0.0
    soma_quadrados = 0.0
    for amostra in amostras:
        soma_quadrados += amostra * amostra
    return math.sqrt(soma_quadrados / len(amostras))


def barra(valor, maximo, tamanho=30):
    if maximo <= 0:
        return ""
    preenchimento = int((valor / maximo) * tamanho)
    preenchimento = max(0, min(tamanho, preenchimento))
    return "█" * preenchimento


# Simula um modelo matemático; não processa áudio real.
def simular_anc(telemetria):
    """Modela um tom, o antirruído e a adaptação do controlador."""
    if telemetria.get("anc_simulado") is not True:
        print("ANC simulado inativo: o estado recebido não é proteção.")
        return "protecao_simulada_inativa"

    try:
        ruido_pontos = int(telemetria.get("noise", 0))
        limite = int(telemetria.get("threshold", 70))
    except (TypeError, ValueError):
        print("Telemetria inválida: ruído ou limite não numérico.")
        return "telemetria_invalida"

    ruido_pontos = max(0, min(100, ruido_pontos))
    amplitude_ruido = ruido_pontos / 100.0
    frequencia_hz = 80
    taxa_amostragem_hz = 1600
    quantidade_amostras = 1600
    amostras_por_bloco = 160
    atraso_caminho_primario_rad = math.radians(20)
    atraso_caminho_secundario_rad = math.radians(30)
    ganho_alto_falante = 0.8
    taxa_adaptacao = 0.12
    pequeno_valor = 0.000001

    peso_seno = 0.0
    peso_cosseno = 0.0
    ruido_primario = []
    sinal_alto_falante = []
    antirruido_no_ouvido = []
    erro_residual = []
    relatorio_blocos = []

    print("\n=== SIMULAÇÃO DIDÁTICA DE ANC FEEDFORWARD ===")
    print("Estado ESP32: PROTEÇÃO / ANC SIMULADO ATIVO")
    print("Entrada: ruído=%d/100 pontos; limite=%d pontos." % (ruido_pontos, limite))
    print(
        "Modelo: tom sintético de %d Hz; duração simulada de 1 segundo."
        % frequencia_hz
    )
    print("Caminho do ruído até o ponto de erro: atraso de fase de 20 graus.")
    print(
        "Caminho do alto-falante: ganho %.2f e atraso de fase de 30 graus."
        % ganho_alto_falante
    )
    print(
        "Adaptação: FxLMS simplificado; saída acústica soma com o ruído "
        "no microfone de erro."
    )
    print("\nEquações do modelo:")
    print("  referência x[n] = seno(2*pi*80*n/1600)")
    print("  ruído d[n] = (pontos/100) * seno(2*pi*80*n/1600 - 20 graus)")
    print("  alto-falante u[n] = peso_seno*seno + peso_cosseno*cosseno")
    print("  erro e[n] = ruído d[n] + antirruído após o caminho acústico")
    print("  a cada amostra, FxLMS ajusta os pesos para diminuir e[n]^2")
    print(
        "\nPassos por amostra: referência -> controlador -> alto-falante "
        "-> erro -> ajuste dos pesos."
    )

    # Ajusta os pesos do controlador para reduzir o erro residual.
    for indice in range(quantidade_amostras):
        fase = 2.0 * math.pi * frequencia_hz * indice / taxa_amostragem_hz
        referencia_seno = math.sin(fase)
        referencia_cosseno = math.cos(fase)
        ruido = amplitude_ruido * math.sin(fase - atraso_caminho_primario_rad)

        referencia_filtrada_seno = math.sin(fase - atraso_caminho_secundario_rad)
        referencia_filtrada_cosseno = math.cos(fase - atraso_caminho_secundario_rad)
        sinal_controle = peso_seno * referencia_seno + peso_cosseno * referencia_cosseno
        antirruido = ganho_alto_falante * (
            peso_seno * referencia_filtrada_seno
            + peso_cosseno * referencia_filtrada_cosseno
        )
        erro = ruido + antirruido

        gradiente_seno = ganho_alto_falante * referencia_filtrada_seno
        gradiente_cosseno = ganho_alto_falante * referencia_filtrada_cosseno
        normalizador = pequeno_valor + gradiente_seno ** 2 + gradiente_cosseno ** 2
        peso_seno -= taxa_adaptacao * erro * gradiente_seno / normalizador
        peso_cosseno -= taxa_adaptacao * erro * gradiente_cosseno / normalizador

        ruido_primario.append(ruido)
        sinal_alto_falante.append(sinal_controle)
        antirruido_no_ouvido.append(antirruido)
        erro_residual.append(erro)

        if (indice + 1) % amostras_por_bloco == 0:
            inicio = indice + 1 - amostras_por_bloco
            fim = indice + 1
            rms_ruido = calcular_rms(ruido_primario[inicio:fim])
            rms_erro = calcular_rms(erro_residual[inicio:fim])
            if rms_erro <= 0.000001:
                reducao_db = 120.0
            else:
                reducao_db = 20.0 * math.log10(max(rms_ruido, 0.000001) / rms_erro)
            relatorio_blocos.append(
                {
                    "tempo": fim / taxa_amostragem_hz,
                    "rms_erro": rms_erro,
                    "reducao_db": reducao_db,
                    "peso_seno": peso_seno,
                    "peso_cosseno": peso_cosseno,
                }
            )

    rms_antes = calcular_rms(ruido_primario)
    rms_depois = calcular_rms(erro_residual)
    if rms_depois <= 0.000001:
        reducao_total_db = 120.0
    else:
        reducao_total_db = 20.0 * math.log10(max(rms_antes, 0.000001) / rms_depois)

    print("\nConvergência do controlador (RMS do erro no microfone de erro):")
    print(" tempo | erro RMS | redução estimada | peso seno | peso cosseno")
    for bloco in relatorio_blocos:
        print(
            " %4.1fs | %7.4f | %7.2f dB        | %8.3f | %11.3f"
            % (
                bloco["tempo"],
                bloco["rms_erro"],
                bloco["reducao_db"],
                bloco["peso_seno"],
                bloco["peso_cosseno"],
            )
        )

    maior_erro_bloco = max(
        (bloco["rms_erro"] for bloco in relatorio_blocos),
        default=0.0,
    )
    print("\nGráfico ASCII do erro residual por bloco (cada linha representa 0,1 s):")
    for bloco in relatorio_blocos:
        print(
            " %.1fs |%s %.4f"
            % (
                bloco["tempo"],
                barra(bloco["rms_erro"], maior_erro_bloco, 24),
                bloco["rms_erro"],
            )
        )

    escala = max(rms_antes, 0.000001)
    print("\nNível médio antes  : %s %.4f" % (barra(rms_antes, escala), rms_antes))
    print("Nível residual após: %s %.4f" % (barra(rms_depois, escala), rms_depois))
    print("Redução estimada neste ponto do modelo: %.2f dB" % reducao_total_db)

    print(
        "\nAmostras finais: ruído d[n] | saída u[n] | antirruído após o caminho "
        "| erro e[n]"
    )
    inicio_final = quantidade_amostras - amostras_por_bloco
    for deslocamento in (0, 5, 10, 15):
        amostra = inicio_final + deslocamento
        print(
            " n=%4d | % .4f | % .4f | % .4f | % .4f"
            % (
                amostra,
                ruido_primario[amostra],
                sinal_alto_falante[amostra],
                antirruido_no_ouvido[amostra],
                erro_residual[amostra],
            )
        )

    print("\nO que o controlador fez:")
    print("1. Modelou o microfone de referência como um tom sintético de 80 Hz.")
    print(
        "2. Calculou uma saída para o alto-falante com pesos "
        "seno/cosseno adaptáveis."
    )
    print("3. Aplicou o atraso e o ganho do caminho acústico secundário modelado.")
    print("4. Somou ruído e antirruído para obter o erro residual.")
    print("5. Ajustou os pesos para reduzir o erro; repetiu isso em cada amostra.")
    print(
        "Limite: não há áudio real do ESP32. O potenciômetro fornece pontos, "
        "não som ou decibéis."
    )
    print(
        "A redução calculada é apenas deste modelo idealizado, "
        "não uma medida de ANC físico."
    )
    return {
        "resultado": "simulacao_fxlms_concluida",
        "ruido_pontos": ruido_pontos,
        "rms_antes": round(rms_antes, 6),
        "rms_depois": round(rms_depois, 6),
        "reducao_estimada_db": round(reducao_total_db, 2),
        "modelo": "tom de 80 Hz com FxLMS simplificado",
    }

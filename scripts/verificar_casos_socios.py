"""Reproduz as nove mensagens das imagens em memória; nunca envia WhatsApp.

Use --moderacao-real para consultar a API OpenAI de moderação.
As respostas aprovadas são determinísticas, sem geração de texto por LLM.
"""

import argparse, copy, json, logging, sys
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import server, worker, tuca_lab
import protecao

MESSAGES = [
    "onde fica o banheiro?",
    "tô com fome",
    "vou conseguir ver o show depois?",
    "perdi o show do matue, vai ter transmissão depois?",
    "vai ter transmissão do show depois?",
    "esse evento tá uma merda",
    "lixo",
    "vcs são pessimos",
    "que porcaria",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--moderacao-real", action="store_true")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    snapshot = {
        "config": {"settings": {}, "rules": [], "knowledge": []},
        "sectors": [],
        "window": [None, None],
        "clock": datetime.now(timezone.utc).isoformat(),
    }
    states = {engine: {} for engine in ("current", "experimental", "jev", "enxuto")}
    rows = []
    from contextlib import ExitStack

    with ExitStack() as stack:
        if not args.moderacao_real:
            for owner in (server, worker):
                stack.enter_context(
                    patch.object(
                        owner, "moderar_texto", return_value={"bloquear": False}
                    )
                )
        for text in MESSAGES:
            results = {
                engine: tuca_lab.run_turn(
                    engine, state, copy.deepcopy(snapshot), text, "text"
                )
                for engine, state in states.items()
            }
            replies = [
                r["messages"][0]["content"] for r in results.values() if r["messages"]
            ]
            assert len(replies) == 4 and len(set(replies)) == 1, {
                "message": text,
                "results": results,
            }
            assert all(r["status"] != "blocked" for r in results.values()), text
            rows.append({"message": text, "reply": replies[0], "results": results})
            print(
                json.dumps(
                    {
                        "message": text,
                        "passed": True,
                        "cards": len(states["current"]["cards"]),
                    },
                    ensure_ascii=True,
                ),
                flush=True,
            )
    payload = {
        "moderacao_real": args.moderacao_real,
        "geracao_llm": False,
        "simulado": True,
        "rows": rows,
    }
    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    (out / "casos-socios-verificados.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# TUCA: respostas verificadas para os casos enviados",
        "",
        "As nove mensagens abaixo foram repetidas na mesma conversa nos quatro motores do laboratório. As respostas foram iguais nos quatro.",
        "",
        "Teste com banco e WhatsApp simulados. "
        + (
            "Moderação real da OpenAI utilizada."
            if args.moderacao_real
            else "Moderação simulada."
        )
        + " Respostas aprovadas em código, sem geração de texto pela IA.",
        "",
    ]
    for i, row in enumerate(rows, 1):
        lines += [f'## {i}. Mensagem: {row["message"]}', "", row["reply"], ""]
    lines += [
        "## O que mudou",
        "",
        "- Fome recebe orientação por setor, sem chamado desnecessário.",
        "- Gravações recebem a informação aprovada pela organização, sem encaminhar para o SAC.",
        "- Banheiro recebe orientação honesta, sem inventar localização.",
        "- Reclamações são acolhidas e registradas; palavrão nesses casos não vira strike.",
        "- “Lixo” na sequência da reclamação é insatisfação. Isoladamente, pede esclarecimento.",
        "- Nenhuma das nove mensagens foi silenciada nessa sequência.",
        "",
        f"O limite permanece em {protecao.LIMITE_RESPONDER} respostas por remetente a cada 10 minutos. O teto de registro e os bloqueios de conteúdo continuam ativos.",
        "",
        "As correções só passam a valer no WhatsApp após o deploy do código.",
    ]
    (ROOT / "docs" / "RESPOSTAS_VERIFICADAS_SOCIOS.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(
        "36 processamentos conferidos; relatorio gerado a partir das respostas obtidas.",
        flush=True,
    )


if __name__ == "__main__":
    main()

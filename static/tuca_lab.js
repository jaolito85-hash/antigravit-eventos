"use strict";
const $ = (id) => document.getElementById(id);
const engines = ["current", "experimental", "jev"];
let tokens = {},
  metadata = {},
  rounds = [],
  busy = false;
const originals = Object.fromEntries(
  engines.map((e) => [e, $(e + "-stream").innerHTML]),
);
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}
function error(message) {
  $("error").textContent = message || "";
  $("error").hidden = !message;
}
function updateControls() {
  $("conversation-progress").textContent = rounds.length
    ? `Próxima mensagem: ${rounds.length + 1} · continuação da mesma conversa`
    : "Mensagem 1: início da conversa";
  const unresolved =
    rounds.length && engines.some((e) => !rounds.at(-1).results[e]);
  $("send").disabled = busy || !tokens.current || !!unresolved;
  $("reset").disabled = busy;
  $("mode").disabled = busy;
  $("export").disabled = !rounds.length;
  $("kind").disabled = busy;
  document
    .querySelectorAll("#jev-form input, #jev-form button")
    .forEach((node) => (node.disabled = busy));
  $("sector").disabled = busy || $("kind").value === "location";
  document
    .querySelectorAll("[data-example]")
    .forEach((b) => (b.disabled = busy));
}
async function api(path, body) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 60000);
  let response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (err) {
    if (err.name === "AbortError")
      throw new Error(
        "O teste demorou demais. Tente novamente nesta variante.",
      );
    throw err;
  } finally {
    clearTimeout(timeout);
  }
  if (
    response.redirected ||
    !response.headers.get("content-type")?.includes("application/json")
  )
    throw new Error("Seu acesso expirou. Entre novamente no painel.");
  const data = await response.json();
  if (!response.ok)
    throw new Error(data.error || "Não foi possível concluir o teste.");
  return data;
}
async function start() {
  if (busy) return;
  busy = true;
  tokens = {};
  updateControls();
  error("");
  $("status").textContent = "Carregando a mesma base para os três...";
  try {
    const data = await api("/api/tuca-lab/start", { mode: $("mode").value });
    tokens = data.tokens;
    metadata = { ...data };
    showJevConfig(data.jev);
    delete metadata.tokens;
    rounds = [];
    $("message").value = "";
    $("counter").textContent = "0 / 2.000";
    engines.forEach((e) => {
      $(e + "-stream").innerHTML = originals[e];
      $(e + "-count").textContent = "0 chamados simulados";
    });
    $("votes").replaceChildren();
    $("evaluations").hidden = true;
    $("sector").replaceChildren(new Option("Sem QR", ""));
    data.sectors.forEach((s) => $("sector").add(new Option(s.name, s.code)));
    $("status").textContent =
      "Nova conversa iniciada. Os três históricos estão vazios.";
    $("snapshot").textContent =
      `Base ${data.mode === "draft" ? "rascunho" : "publicada"} congelada · ${data.snapshot} · código ${data.revision}`;
  } catch (err) {
    error(err.message);
    $("status").textContent =
      "Comparação indisponível. Use Iniciar nova conversa para tentar novamente.";
  } finally {
    busy = false;
    updateControls();
  }
}
function addRound(engine, round) {
  const stream = $(engine + "-stream");
  stream.querySelector(".empty")?.remove();
  const node = el("section", "turn");
  node.dataset.round = round.number;
  node.append(
    el("div", "round", `RODADA ${String(round.number).padStart(2, "0")}`),
  );
  node.append(
    el(
      "div",
      "bubble user",
      round.kind === "location" ? "📍 " + round.content : round.content,
    ),
  );
  const answer = el("div", "answer");
  answer.append(el("div", "thinking", "Pensando na resposta..."));
  node.append(answer);
  stream.append(node);
  stream.scrollTop = stream.scrollHeight;
  return answer;
}
function renderResult(engine, target, result) {
  target.replaceChildren();
  if (!result.messages.length)
    target.append(el("p", "thinking", "Este Tuca não respondeu nesta rodada."));
  result.messages.forEach((m) => {
    if (m.type === "text") target.append(el("div", "bubble bot", m.content));
    else if (m.type === "image") {
      try {
        const url = new URL(m.url);
        if (url.protocol !== "https:") return;
        const a = el(
          "a",
          "official-image",
          m.content || "Abrir imagem oficial enviada pelo Tuca",
        );
        a.href = url.href;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        target.append(a);
      } catch (_) {
        target.append(el("p", "thinking", "Imagem com endereço inválido."));
      }
    }
  });
  const tags = el("div", "result-tags");
  [
    result.jev &&
      {
        ok: "JEV consultado",
        bypass: "Protocolo direto",
        unavailable: "JEV indisponível: reserva",
      }[result.jev.status],
    result.urgency,
    result.action,
    result.sector && "Local: " + result.sector,
    `${(result.elapsed_ms / 1000).toFixed(1)} s`,
  ]
    .filter(Boolean)
    .forEach((t) =>
      tags.append(
        el("span", "result-tag" + (t === "Critico" ? " critical" : ""), t),
      ),
    );
  target.append(tags);
  const details = el("details", "details");
  details.append(el("summary", "", "Ver fontes e decisão"));
  details.append(el("p", "", result.method));
  if (result.sources.length)
    result.sources.forEach((s) => {
      details.append(el("strong", "", s.title));
      details.append(el("blockquote", "", s.quote));
    });
  else
    details.append(
      el(
        "p",
        "",
        engine === "current"
          ? "O motor atual não expõe as fontes usadas neste fluxo."
          : "Nenhum trecho de ficha foi usado nesta resposta.",
      ),
    );
  result.notes.forEach((n) => details.append(el("p", "", n)));
  if (result.jev) {
    const j = result.jev;
    if (j.status === "ok")
      $("jev-status").textContent = "JEV conectado · " + j.model;
    if (j.status === "unavailable")
      $("jev-status").textContent =
        "JEV indisponível nesta rodada. Veja os detalhes da resposta.";
    const labels = {
      ok: "JEV consultado",
      bypass: "Protocolo direto, sem JEV",
      unavailable: "JEV indisponível: reserva ativa",
    };
    details.append(el("strong", "jev-label", labels[j.status] || j.status));
    if (j.model) details.append(el("p", "", "Modelo: " + j.model));
    const names = {
      intent: "Intenção",
      danger: "Risco físico",
      sector: "Setor",
      has_location: "Localização explícita",
      conflict: "Conflito nas fontes",
    };
    Object.entries(j.decisions || {}).forEach(([name, answer]) => {
      const line =
        answer.type === "noul"
          ? `${names[name] || "Relevância " + name.replace("source_", "")}: probabilidade ${(answer.noul * 100).toFixed(1)}%`
          : `${names[name] || name}: ${answer.choice} · confiança ${answer.confidence.toFixed(2)}`;
      details.append(el("p", "decision-line", line));
      if (answer.probabilities) {
        const distribution = el("details", "distribution");
        distribution.append(el("summary", "", "Ver probabilidades das opções"));
        Object.entries(answer.probabilities)
          .sort((a, b) => b[1] - a[1])
          .forEach(([option, value]) =>
            distribution.append(
              el("p", "", `${option}: ${(value * 100).toFixed(1)}%`),
            ),
          );
        details.append(distribution);
      }
    });
    details.append(
      el(
        "p",
        "",
        "Probabilidades estimadas pelo modelo. Confiança resume a distribuição; não garante que a decisão esteja correta.",
      ),
    );
  }
  target.append(details);
  $(engine + "-count").textContent =
    `${result.cards} chamado${result.cards === 1 ? "" : "s"} simulado${result.cards === 1 ? "" : "s"}`;
  const stream = $(engine + "-stream");
  stream.scrollTop = stream.scrollHeight;
}
function addVote(round) {
  if (round.voteAdded) return;
  round.voteAdded = true;
  $("evaluations").hidden = false;
  const row = el("div", "vote");
  const label = el("label", "", `Rodada ${round.number}`);
  label.htmlFor = "vote-" + round.number;
  const select = el("select");
  select.id = label.htmlFor;
  [
    ["", "Qual resposta você usaria?"],
    ["current", "Tuca atual"],
    ["experimental", "Tuca experimental"],
    ["jev", "Tuca JEV + LLM"],
    ["tie", "As três estão boas"],
    ["neither", "Nenhuma está pronta"],
  ].forEach(([v, t]) => select.add(new Option(t, v)));
  select.addEventListener("change", () => (round.vote = select.value));
  const input = el("input");
  input.type = "text";
  input.maxLength = 800;
  input.placeholder = "O que acertou ou faltou?";
  input.setAttribute("aria-label", `Observação sobre a rodada ${round.number}`);
  input.addEventListener("input", () => (round.note = input.value));
  row.append(label, select, input);
  $("votes").append(row);
}
async function requestSide(engine, round, target) {
  target.replaceChildren(el("div", "thinking", "Pensando na resposta..."));
  try {
    const data = await api("/api/tuca-lab/turn", {
      token: tokens[engine],
      content: round.content,
      kind: round.kind,
    });
    tokens[engine] = data.token;
    round.results[engine] = data.result;
    delete round.errors[engine];
    renderResult(engine, target, data.result);
  } catch (err) {
    round.errors[engine] = err.message;
    target.replaceChildren(el("p", "notice", err.message));
    const retry = el("button", "button ghost", "Tentar somente este Tuca");
    retry.type = "button";
    retry.onclick = async () => {
      if (busy) return;
      busy = true;
      updateControls();
      await requestSide(engine, round, target);
      busy = false;
      complete(round);
    };
    target.append(retry);
  }
}
function complete(round) {
  if (engines.every((e) => round.results[e])) {
    addVote(round);
    $("status").textContent =
      `Mensagem ${round.number} respondida. Seu próximo envio continua esta conversa.`;
  } else
    $("status").textContent =
      "Uma variante falhou. Tente novamente nela ou inicie outra comparação.";
  updateControls();
}
async function send(event) {
  event?.preventDefault();
  if ($("send").disabled) return;
  let content = $("message").value.trim();
  if (!content) return;
  if (
    $("kind").value === "location" &&
    !/^\s*-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?\s*$/.test(content)
  ) {
    error("Use latitude,longitude. Exemplo: -23.3312,-51.1925");
    return;
  }
  if ($("kind").value === "text" && $("sector").value)
    content = `#SETOR:${$("sector").value}\n${content}`;
  if (content.length > 2000) {
    error("A mensagem com o QR precisa ter até 2.000 caracteres.");
    return;
  }
  busy = true;
  error("");
  const round = {
    number: rounds.length + 1,
    at: new Date().toISOString(),
    content,
    kind: $("kind").value,
    results: {},
    errors: {},
    vote: "",
    note: "",
  };
  rounds.push(round);
  updateControls();
  const targets = Object.fromEntries(
    engines.map((e) => [e, addRound(e, round)]),
  );
  $("status").textContent = "Comparando as três respostas...";
  $("message").value = "";
  $("counter").textContent = "0 / 2.000";
  $("sector").value = "";
  await Promise.allSettled(
    engines.map((e) => requestSide(e, round, targets[e])),
  );
  busy = false;
  complete(round);
  $("message").focus();
}
$("compose-form").addEventListener("submit", send);
$("message").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    send();
  }
});
$("message").addEventListener("input", () => {
  $("counter").textContent = `${$("message").value.length} / 2.000`;
});
$("reset").addEventListener("click", start);
$("mode").addEventListener("change", start);
$("kind").addEventListener("change", () => {
  $("message").placeholder =
    $("kind").value === "location"
      ? "Latitude,longitude. Ex.: -23.3312,-51.1925"
      : "Escreva como alguém no festival...";
  updateControls();
});
document.querySelectorAll("[data-example]").forEach((button) =>
  button.addEventListener("click", () => {
    $("kind").value = "text";
    $("message").value = button.dataset.example;
    $("message").dispatchEvent(new Event("input"));
    updateControls();
    $("message").focus();
  }),
);
$("export").addEventListener("click", () => {
  const report = {
    title: "Comparação TUCA",
    exported_at: new Date().toISOString(),
    simulated: true,
    metadata,
    rounds: rounds.map(({ voteAdded, ...r }) => r),
  };
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }),
  );
  const a = el("a");
  a.href = url;
  a.download = `comparacao-tuca-${new Date().toISOString().slice(0, 10)}.json`;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
function showJevConfig(config) {
  if (!config) return;
  $("jev-status").textContent = config.configured
    ? `Chave configurada no ${config.key_source}. Conexão ainda não verificada.`
    : "Sem chave: configure para testar o JEV";
  $("jev-model").value = config.model;
  $("jev-intent").value = config.intent_threshold;
  $("jev-location").value = config.location_threshold;
  $("jev-source").value = config.source_threshold;
  $("jev-timeout").value = config.timeout;
}
async function saveJev(remove = false) {
  if (busy) return;
  busy = true;
  updateControls();
  try {
    const data = await api("/api/tuca-lab/jev-config", {
      api_key: remove ? "" : $("jev-key").value.trim(),
      remove_key: remove,
      model: $("jev-model").value.trim(),
      intent_threshold: Number($("jev-intent").value),
      location_threshold: Number($("jev-location").value),
      source_threshold: Number($("jev-source").value),
      timeout: Number($("jev-timeout").value),
    });
    $("jev-key").value = "";
    showJevConfig(data);
    $("jev-feedback").textContent =
      "Salvo. Inicie uma nova comparação para aplicar os limites. A chave configurada é usada na próxima chamada.";
  } catch (err) {
    $("jev-feedback").textContent = err.message;
  } finally {
    busy = false;
    updateControls();
  }
}
$("jev-form").addEventListener("submit", (event) => {
  event.preventDefault();
  saveJev();
});
$("jev-remove").addEventListener("click", () => saveJev(true));
$("jev-test").addEventListener("click", async () => {
  if (busy) return;
  busy = true;
  updateControls();
  $("jev-feedback").textContent =
    "Consultando o JEV com uma saudação fictícia...";
  try {
    const data = await api("/api/tuca-lab/jev-test", {});
    $("jev-feedback").textContent = data.message + " Modelo: " + data.model;
    $("jev-status").textContent = "Conexão verificada: " + data.model;
  } catch (err) {
    $("jev-feedback").textContent = err.message;
  } finally {
    busy = false;
    updateControls();
  }
});
start();

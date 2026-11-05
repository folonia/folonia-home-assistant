// La page Folonia, dans la barre latérale de Home Assistant.
//
// Un élément personnalisé, sans compilation ni dépendance : Home Assistant lui donne `hass`,
// `narrow` et `panel`, comme à tout panneau personnalisé. Il n'utilise aucun élément interne
// de Home Assistant (`ha-*`) : interrupteurs, puces et champs sont les siens, aux couleurs du
// thème (variables CSS de Home Assistant), clair ou sombre.
//
// La page ne décide de rien : elle montre ce que l'intégration lui rend (`folonia/settings`),
// garde les changements jusqu'à « Enregistrer », puis les envoie (`folonia/save`,
// `folonia/secret`). L'intégration recoupe tout avec la liste permise et applique les règles.
// Les alias d'un appareil, ceux d'Assist, se modifient dans une petite fenêtre et s'enregistrent
// à part (`folonia/aliases`) : ils vont au registre des entités de Home Assistant, pas dans les
// réglages de Folonia. Tout texte venu de Home Assistant (noms d'appareils, pièces, alias,
// journal) est échappé.

const TAG = "folonia-panel";
const EXPOSE_URL = "/config/voice-assistants/expose";
const LOGBOOK_URL = "/logbook";
const AREAS_URL = "/config/areas";
/** Les alias d'un appareil que la page enregistre, au plus, et leur longueur : ceux de l'intégration. */
const MAX_ALIASES = 20;
const MAX_ALIAS = 100;

const ICONS = {
  lampe:
    '<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5c.6.6 1 1.4 1 2.5h6c0-1.1.4-1.9 1-2.5A6 6 0 0 0 12 3z"/>',
  porte: '<path d="M6 21V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v17M3 21h18M14 12h.01"/>',
  garage: '<path d="M3 21V9l9-5 9 5v12M7 21v-8h10v8M7 16h10"/>',
  serrure: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  alarme: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>',
  thermo: '<path d="M14 14.8V5a2 2 0 0 0-4 0v9.8a4 4 0 1 0 4 0z"/>',
  volet: '<rect x="4" y="3" width="16" height="18" rx="1"/><path d="M4 8h16M4 13h16"/>',
  prise: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M10 9v3M14 9v3M12 15v1"/>',
  personne: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6"/>',
  fenetre: '<rect x="4" y="3" width="16" height="18" rx="1"/><path d="M12 3v18M4 12h16"/>',
  capteur: '<circle cx="12" cy="12" r="3"/><path d="M5 5a10 10 0 0 0 0 14M19 5a10 10 0 0 1 0 14"/>',
  media: '<rect x="3" y="5" width="18" height="12" rx="2"/><path d="M8 21h8"/>',
  aspi: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="2"/>',
  scene: '<path d="M8 5v14l11-7z"/>',
  meteo: '<path d="M7 18h10a4 4 0 0 0 0-8 6 6 0 0 0-11.5 1.5A3.5 3.5 0 0 0 7 18z"/>',
};
const SEARCH_ICON =
  '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>';
const PEN_ICON =
  '<svg class="pen" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/></svg>';
const MENU_ICON =
  '<svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M3 6h18v2H3zm0 5h18v2H3zm0 5h18v2H3z"/></svg>';

/** Les refus de l'intégration, dits ici ; à défaut, son propre message. */
const ERRORS = {
  invalid_lock_code: "Le code est fait de quatre à huit chiffres.",
  invalid_lock_phrase:
    "Le mot de passe compte au moins quatre lettres ou chiffres, et soixante-quatre caractères au plus.",
  lock_code_required:
    "Choisissez un code ou un mot de passe : une protection cochée porte sur un appareil partagé (serrure, alarme, portail, porte de garage, présence, porte ou fenêtre). Sinon, décochez-la, ou laissez l’appareil sans code.",
  not_loaded: "L’intégration Folonia n’est pas chargée. Vérifiez-la dans Paramètres, Appareils et services.",
  unauthorized: "Cette page est réservée aux administrateurs de Home Assistant.",
  alias_not_allowed:
    "Cet appareil n’est pas exposé aux assistants vocaux : ses alias ne se modifient pas ici.",
  alias_not_editable:
    "Cet appareil n’a pas d’identifiant unique dans Home Assistant : ses alias ne se modifient pas.",
  invalid_format: "Home Assistant a refusé la demande. Rechargez la page et réessayez.",
};

const FILTERS = [
  ["all", "Tous"],
  ["shared", "Partagés"],
  ["sensitive", "Sensibles"],
  ["exempt", "Sans code"],
];
const FIELDS = ["read", "control", "exempt"];

/** Échappe un texte avant de l'insérer dans le HTML (contenu ou attribut). */
function esc(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );
}

function capitalize(text) {
  return text ? text.charAt(0).toLocaleUpperCase("fr") + text.slice(1) : text;
}

/** Un alias tel qu'il est saisi : une ligne, espaces réduits, borné. */
function cleanAlias(text) {
  return String(text ?? "").replace(/\s+/g, " ").trim().slice(0, MAX_ALIAS);
}

function plural(n, one, many) {
  return `${n} ${n > 1 ? many : one}`;
}

function iconFor(device) {
  const cls = device.device_class;
  switch (device.domain) {
    case "light":
      return "lampe";
    case "lock":
      return "serrure";
    case "alarm_control_panel":
      return "alarme";
    case "climate":
    case "water_heater":
      return "thermo";
    case "person":
    case "device_tracker":
      return "personne";
    case "media_player":
      return "media";
    case "vacuum":
      return "aspi";
    case "scene":
    case "script":
      return "scene";
    case "weather":
      return "meteo";
    case "cover":
      if (["garage", "garage_door", "gate"].includes(cls)) return "garage";
      if (cls === "door") return "porte";
      if (cls === "window") return "fenetre";
      return "volet";
    case "binary_sensor":
      if (["garage_door", "door", "opening"].includes(cls)) return "porte";
      if (cls === "window") return "fenetre";
      return "capteur";
    case "sensor":
      return cls === "temperature" ? "thermo" : "capteur";
    default:
      return "prise";
  }
}

function svg(name, size = 18) {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;
}

function toggle(attrs, on, disabled, label) {
  return `<label class="sw"><input type="checkbox" role="switch" ${attrs} ${on ? "checked" : ""} ${
    disabled ? "disabled" : ""
  } aria-label="${esc(label)}"><span></span></label>`;
}

const STYLE = `
  :host {
    display: block;
    height: 100%;
    --f-fg: var(--primary-text-color, #212121);
    --f-muted: var(--secondary-text-color, #727272);
    --f-bg: var(--primary-background-color, #fafafa);
    --f-card: var(--card-background-color, var(--ha-card-background, #fff));
    --f-line: var(--divider-color, rgba(0, 0, 0, 0.12));
    --f-accent: var(--primary-color, #03a9f4);
    --f-accent-fg: var(--text-primary-color, #fff);
    --f-chip: var(--secondary-background-color, #e5e5e5);
    --f-ok: var(--success-color, #43a047);
    --f-warn: var(--warning-color, #ffa600);
    --f-err: var(--error-color, #db4437);
    --f-warn-text: color-mix(in srgb, var(--f-warn) 62%, var(--f-fg));
    --f-warn-bg: color-mix(in srgb, var(--f-warn) 14%, var(--f-card));
    --f-err-text: color-mix(in srgb, var(--f-err) 80%, var(--f-fg));
    --f-err-bg: color-mix(in srgb, var(--f-err) 12%, var(--f-card));
    --f-on: var(--switch-checked-color, var(--f-accent));
    --f-off: color-mix(in srgb, var(--switch-unchecked-track-color, var(--f-fg)) 32%, transparent);
    --f-knob: var(--switch-unchecked-button-color, #fafafa);
    --f-night: #1e2a5a;
    color: var(--f-fg);
    background: var(--f-bg);
    font-size: 14px;
    line-height: 1.45;
    -webkit-font-smoothing: antialiased;
  }
  * { box-sizing: border-box; }
  [hidden] { display: none !important; }
  a { color: var(--f-accent); }
  .layout { height: 100%; display: flex; flex-direction: column; position: relative; }
  .gutter { padding-left: 16px; padding-right: 16px; }

  header {
    flex: none;
    background: var(--app-header-background-color, var(--f-accent));
    color: var(--app-header-text-color, var(--f-accent-fg));
    padding-top: var(--safe-area-inset-top, 0px);
    border-bottom: var(--app-header-border-bottom, none);
  }
  .top { display: flex; align-items: center; gap: 8px; min-height: 56px; max-width: 64rem; margin: 0 auto; }
  .menu { display: grid; place-items: center; width: 40px; height: 40px; margin-left: -8px; border: 0; border-radius: 50%; background: none; color: inherit; cursor: pointer; }
  .menu:hover { background: color-mix(in srgb, currentColor 10%, transparent); }
  h1 { font-size: 20px; font-weight: 400; margin: 0; flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .link { display: flex; align-items: center; gap: 8px; font-size: 13px; white-space: nowrap; min-width: 0; }
  .link span:last-child { overflow: hidden; text-overflow: ellipsis; }
  .dot { flex: none; width: 10px; height: 10px; border-radius: 50%; background: var(--f-muted); box-shadow: 0 0 0 2px var(--f-night), 0 0 0 4px color-mix(in srgb, currentColor 35%, transparent); }
  .dot.on { background: var(--f-ok); }
  .dot.wait { background: var(--f-warn); }
  .dot.bad { background: var(--f-err); }
  nav { display: flex; gap: 4px; max-width: 64rem; margin: 0 auto; overflow-x: auto; scrollbar-width: none; }
  nav button { font: inherit; font-size: 14px; font-weight: 500; color: inherit; opacity: 0.78; background: none; border: 0; border-bottom: 2px solid transparent; padding: 10px 12px; cursor: pointer; white-space: nowrap; }
  nav button[aria-selected="true"] { opacity: 1; border-bottom-color: currentColor; }

  .scroll { flex: 1; min-height: 0; overflow-y: auto; }
  main { max-width: 64rem; margin: 0 auto; padding-top: 16px; padding-bottom: 24px; display: grid; gap: 16px; }
  section { display: grid; gap: 16px; align-content: start; }
  .card { background: var(--f-card); border: 1px solid var(--f-line); border-radius: var(--ha-card-border-radius, 12px); box-shadow: var(--ha-card-box-shadow, none); min-width: 0; }
  .pad { padding: 16px; display: grid; gap: 12px; }
  h2 { font-size: 16px; font-weight: 500; margin: 0; }
  p { margin: 0; }
  .hint { font-size: 13px; color: var(--f-muted); }
  .note { padding: 0 4px; }
  .banner { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; padding: 12px 16px; border-radius: 12px; background: var(--f-warn-bg); color: var(--f-warn-text); font-size: 14px; }
  .banner p { flex: 1 1 16rem; }
  .banner.err { background: var(--f-err-bg); color: var(--f-err-text); }
  .banner .btn { flex: none; }

  .access { display: flex; align-items: center; gap: 12px; }
  .access div { flex: 1; min-width: 0; }
  .access p { font-size: 13px; color: var(--f-muted); margin-top: 2px; }
  .summary { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
  .stat { display: grid; gap: 2px; padding: 10px 12px; border-radius: 10px; background: var(--f-chip); }
  .stat b { font-size: 22px; font-weight: 500; font-variant-numeric: tabular-nums; }
  .stat span { font-size: 12px; color: var(--f-muted); }

  .tools { display: grid; gap: 10px; padding: 12px; border-bottom: 1px solid var(--f-line); }
  .search { display: flex; align-items: center; gap: 8px; background: var(--f-chip); border-radius: 10px; padding: 0 12px; color: var(--f-muted); }
  .search input { flex: 1; min-width: 0; font: inherit; font-size: 15px; border: 0; background: none; color: var(--f-fg); padding: 10px 0; outline: none; }
  .search:focus-within { outline: 2px solid var(--f-accent); }
  .chips { display: flex; gap: 6px; flex-wrap: wrap; }
  .chip { font: inherit; font-size: 13px; border: 1px solid var(--f-line); background: var(--f-card); color: var(--f-fg); border-radius: 999px; padding: 5px 12px; cursor: pointer; }
  .chip[aria-pressed="true"] { background: var(--f-accent); color: var(--f-accent-fg); border-color: var(--f-accent); }
  .row-tools { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  select { font: inherit; font-size: 13px; color: var(--f-fg); background: var(--f-card); border: 1px solid var(--f-line); border-radius: 8px; padding: 6px 8px; max-width: 100%; }
  .count { margin-left: auto; font-size: 13px; color: var(--f-muted); font-variant-numeric: tabular-nums; }

  .head, .item { display: grid; grid-template-columns: minmax(0, 1fr) repeat(3, 76px); align-items: center; gap: 4px; padding: 8px 12px; }
  .head { font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: var(--f-muted); border-bottom: 1px solid var(--f-line); }
  .head span:not(:first-child) { text-align: center; }
  .list { max-height: min(60vh, 34rem); overflow-y: auto; overscroll-behavior: contain; }
  .item { border-bottom: 1px solid var(--f-line); }
  .item:last-child { border-bottom: 0; }
  .who { display: flex; gap: 10px; align-items: center; min-width: 0; }
  .ico { flex: none; width: 34px; height: 34px; border-radius: 50%; display: grid; place-items: center; background: var(--f-chip); color: var(--f-muted); }
  .ico.sens { background: var(--f-warn-bg); color: var(--f-warn-text); }
  .names { min-width: 0; }
  button.names { font: inherit; color: inherit; text-align: left; background: none; border: 0; padding: 2px 4px; margin: -2px -4px; border-radius: 8px; cursor: pointer; }
  button.names:hover .pen { color: var(--f-accent); }
  button.names:focus-visible { outline: 2px solid var(--f-accent); }
  .title { display: flex; align-items: center; gap: 4px; min-width: 0; }
  .names b { display: block; min-width: 0; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pen { flex: none; color: var(--f-muted); opacity: 0.8; }
  .names small { display: block; color: var(--f-muted); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .names .aka { font-style: italic; }
  .names .warn { color: var(--f-warn-text); }
  .vh { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
  .cell { display: grid; place-items: center; color: var(--f-muted); }
  .empty { padding: 24px 16px; text-align: center; color: var(--f-muted); display: grid; gap: 8px; justify-items: center; }
  .foot { padding: 10px 12px; border-top: 1px solid var(--f-line); }

  .sw { position: relative; display: inline-block; width: 36px; height: 20px; flex: none; }
  .sw input { position: absolute; inset: -8px; width: calc(100% + 16px); height: calc(100% + 16px); opacity: 0; margin: 0; cursor: pointer; z-index: 1; }
  .sw input:disabled { cursor: default; }
  .sw span { position: absolute; inset: 0; border-radius: 999px; background: var(--f-off); transition: background 0.15s; pointer-events: none; }
  .sw span::after { content: ""; position: absolute; top: 2px; left: 2px; width: 16px; height: 16px; border-radius: 50%; background: var(--f-knob); box-shadow: 0 1px 2px rgb(0 0 0 / 0.35); transition: transform 0.15s; }
  .sw input:checked + span { background: var(--f-on); }
  .sw input:checked + span::after { transform: translateX(16px); background: #fff; }
  .sw input:disabled + span { opacity: 0.4; }
  .sw input:focus-visible + span { outline: 2px solid var(--f-accent); outline-offset: 3px; }

  .field { display: grid; gap: 6px; }
  .field-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .field-head label { font-weight: 500; }
  .badge { font-size: 12px; font-weight: 500; padding: 1px 8px; border-radius: 999px; background: var(--f-chip); color: var(--f-muted); }
  .badge.set { color: var(--f-ok); background: color-mix(in srgb, var(--f-ok) 14%, var(--f-card)); }
  .badge.clear { color: var(--f-warn-text); background: var(--f-warn-bg); }
  .input-row { display: flex; gap: 8px; align-items: center; max-width: 36rem; }
  .input-row input { flex: 1; min-width: 0; font: inherit; font-size: 15px; letter-spacing: 0.04em; color: var(--f-fg); background: var(--f-chip); border: 1px solid transparent; border-radius: 10px; padding: 10px 12px; }
  .input-row input:focus { outline: 2px solid var(--f-accent); }
  .input-row input[aria-invalid="true"] { border-color: var(--f-err); }
  .input-row input:disabled { opacity: 0.5; }
  .error { font-size: 13px; color: var(--f-err-text); }
  .advice { font-size: 13px; color: var(--f-warn-text); }
  .opt { display: flex; gap: 12px; align-items: flex-start; }
  .opt div { flex: 1; min-width: 0; }
  .opt b { font-weight: 500; display: block; }
  .opt p { font-size: 13px; color: var(--f-muted); margin-top: 2px; }
  .opt .sw { margin-top: 2px; }
  .warnbox { background: var(--f-warn-bg); color: var(--f-warn-text); border-radius: 10px; padding: 10px 12px; font-size: 13px; }
  .lockstate { display: flex; gap: 10px; align-items: flex-start; }
  .lockstate .dot { margin-top: 5px; box-shadow: none; }

  .log { list-style: none; margin: 0; padding: 0; }
  .log li { display: grid; grid-template-columns: 76px minmax(0, 1fr); gap: 10px; padding: 10px 16px; border-bottom: 1px solid var(--f-line); }
  .log li:last-child { border-bottom: 0; }
  .log time { font-size: 13px; color: var(--f-muted); font-variant-numeric: tabular-nums; padding-top: 1px; }
  .log small { display: block; color: var(--f-muted); font-size: 12px; }
  .log .bad { color: var(--f-warn-text); font-weight: 500; }
  .row-actions { display: flex; gap: 8px; align-items: center; justify-content: space-between; flex-wrap: wrap; }

  .btn { font: inherit; font-size: 14px; font-weight: 500; border-radius: 999px; padding: 8px 16px; cursor: pointer; border: 1px solid var(--f-line); background: var(--f-card); color: var(--f-fg); white-space: nowrap; }
  .btn.small { padding: 6px 12px; font-size: 13px; }
  .btn.primary { background: var(--f-accent); color: var(--f-accent-fg); border-color: var(--f-accent); }
  .btn:disabled { opacity: 0.55; cursor: default; }
  .btn:focus-visible, .chip:focus-visible, nav button:focus-visible, .menu:focus-visible { outline: 2px solid var(--f-accent); outline-offset: 2px; }

  .savebar { flex: none; background: var(--f-card); border-top: 1px solid var(--f-line); box-shadow: 0 -4px 16px rgb(0 0 0 / 0.08); padding-top: 10px; padding-bottom: calc(10px + var(--safe-area-inset-bottom, 0px)); }
  .savebar .in { max-width: 64rem; margin: 0 auto; display: flex; align-items: center; gap: 8px; }
  .savebar p { flex: 1 1 0; min-width: 0; font-size: 14px; }
  .savebar .error { max-width: 64rem; margin: 6px auto 0; }
  dialog.sheet { border: 0; padding: 0; width: min(28rem, calc(100% - 32px)); max-height: calc(100% - 32px); overflow-y: auto; border-radius: 16px; background: var(--f-card); color: var(--f-fg); box-shadow: 0 8px 32px rgb(0 0 0 / 0.3); }
  dialog.sheet::backdrop { background: rgb(0 0 0 / 0.45); }
  .sheet-in { padding: 16px; display: grid; gap: 12px; }
  .sheet-in:focus { outline: none; }
  .sheet-head { display: flex; align-items: flex-start; gap: 8px; }
  .sheet-head div { flex: 1; min-width: 0; }
  .sheet-head p { font-size: 13px; color: var(--f-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .x { flex: none; display: grid; place-items: center; width: 36px; height: 36px; margin: -6px -8px 0 0; border: 0; border-radius: 50%; background: none; color: var(--f-muted); font-size: 22px; line-height: 1; cursor: pointer; }
  .x:hover { background: var(--f-chip); }
  .pills { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 6px; }
  .pill { display: inline-flex; align-items: center; gap: 2px; max-width: 100%; padding: 3px 4px 3px 12px; border-radius: 999px; background: var(--f-chip); font-size: 14px; }
  .pill span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pill button { flex: none; display: grid; place-items: center; width: 28px; height: 28px; border: 0; border-radius: 50%; background: none; color: var(--f-muted); font-size: 18px; line-height: 1; cursor: pointer; }
  .pill button:hover { background: color-mix(in srgb, var(--f-fg) 10%, transparent); color: var(--f-fg); }
  .sheet .input-row input { letter-spacing: 0; }
  .area-al { font-size: 13px; color: var(--f-muted); border-top: 1px solid var(--f-line); padding-top: 12px; }
  .sheet-actions { display: flex; justify-content: flex-end; gap: 8px; }
  .x:focus-visible, .pill button:focus-visible { outline: 2px solid var(--f-accent); outline-offset: 1px; }

  .toast { position: absolute; left: 50%; bottom: 24px; transform: translateX(-50%); background: var(--f-fg); color: var(--f-bg); padding: 8px 16px; border-radius: 8px; font-size: 14px; z-index: 3; box-shadow: 0 2px 8px rgb(0 0 0 / 0.25); }

  @media (max-width: 480px) {
    .head, .item { grid-template-columns: minmax(0, 1fr) repeat(3, 60px); padding-left: 10px; padding-right: 10px; gap: 2px; }
    .head { font-size: 11px; letter-spacing: 0; text-transform: none; line-height: 1.2; column-gap: 6px; }
    .head span:not(:first-child) { font-size: 10px; }
    .head span:not(:first-child) { text-align: center; }
    .names b { white-space: normal; }
    .names small { white-space: normal; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
    .names .aka { display: block; white-space: nowrap; }
    .savebar p { font-size: 13px; }
    .savebar .btn { padding: 8px 14px; }
    .ico { width: 30px; height: 30px; }
    .who { gap: 8px; }
    .log li { grid-template-columns: 64px minmax(0, 1fr); padding-left: 12px; padding-right: 12px; }
    dialog.sheet { width: 100%; max-width: 100%; margin: auto 0 0; border-radius: 16px 16px 0 0; }
    .sheet-in { padding-bottom: calc(16px + var(--safe-area-inset-bottom, 0px)); }
  }
  @media (prefers-reduced-motion: reduce) { .sw span, .sw span::after { transition: none; } }
`;

class FoloniaPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._narrow = false;
    this._data = null;
    this._error = null;
    this._tab = "devices";
    this._filter = "all";
    this._query = "";
    this._area = "";
    this._sort = "area";
    /** Changements non enregistrés : entité → { read, control, exempt } voulus. */
    this._changes = new Map();
    /** Protections changées, non enregistrées. */
    this._prot = {};
    /** Secrets saisis (jamais gardés ailleurs que dans ces champs) et effacements demandés. */
    this._draft = { code: "", phrase: "" };
    this._clear = { code: false, phrase: false };
    this._fieldErrors = {};
    this._saveError = "";
    this._advice = "";
    this._busy = false;
    this._journal = null;
    this._built = false;
    this._loading = false;
    this._liveKey = "";
    /** Les alias en cours de modification : appareil, liste voulue, saisie, erreur. */
    this._alias = null;
  }

  // --- Ce que Home Assistant donne ----------------------------------------------------------

  set hass(hass) {
    this._hass = hass;
    if (!this._built) return;
    if (!this._data && !this._loading && !this._error) this._load();
    this._renderLive();
  }

  get hass() {
    return this._hass;
  }

  set narrow(narrow) {
    this._narrow = Boolean(narrow);
    if (this._built) this._renderLive();
  }

  get narrow() {
    return this._narrow;
  }

  set panel(panel) {
    this._panel = panel;
  }

  get panel() {
    return this._panel;
  }

  connectedCallback() {
    if (!this._built) this._build();
    if (this._hass && !this._data && !this._loading) this._load();
    this._renderLive();
  }

  // --- Données ------------------------------------------------------------------------------

  async _load() {
    if (!this._hass) return;
    this._loading = true;
    try {
      this._ingest(await this._hass.callWS({ type: "folonia/settings" }));
      this._error = null;
    } catch (err) {
      this._error = this._message(err);
    }
    this._loading = false;
    this._renderAll();
  }

  /** Une réponse de l'intégration : ce qui est enregistré. Les changements en cours restent. */
  _ingest(data) {
    this._data = data;
    this._byId = new Map(data.devices.map((d) => [d.entity_id, d]));
    for (const [id, wanted] of this._changes) {
      const device = this._byId.get(id);
      if (!device || FIELDS.every((f) => wanted[f] === this._savedOf(device)[f])) {
        this._changes.delete(id);
      }
    }
    for (const key of Object.keys(this._prot)) {
      if (this._prot[key] === data.protections[key]) delete this._prot[key];
    }
  }

  /** Les choix enregistrés d'un appareil, tels que la page les montre : lire suit commander. */
  _savedOf(device) {
    return {
      read: device.read || device.control,
      control: device.control,
      exempt: device.exempt,
    };
  }

  _choiceOf(device) {
    return this._changes.get(device.entity_id) || this._savedOf(device);
  }

  _protection(key) {
    return key in this._prot ? this._prot[key] : this._data.protections[key];
  }

  _changeCount() {
    if (!this._data) return 0;
    let count = 0;
    for (const [id, wanted] of this._changes) {
      const saved = this._savedOf(this._byId.get(id));
      count += FIELDS.filter((f) => wanted[f] !== saved[f]).length;
    }
    count += Object.keys(this._prot).length;
    count += ["code", "phrase"].filter((k) => this._draft[k] || this._clear[k]).length;
    return count;
  }

  _message(err) {
    const code = err && err.code;
    return ERRORS[code] || (err && err.message) || "Home Assistant n’a pas répondu. Réessayez.";
  }

  // --- Construction -------------------------------------------------------------------------

  _build() {
    this._built = true;
    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <div class="layout">
        <header>
          <div class="gutter">
            <div class="top">
              <button class="menu" type="button" id="menu" aria-label="Menu" hidden>${MENU_ICON}</button>
              <h1>Folonia</h1>
              <span class="link" id="link" role="status"></span>
            </div>
            <nav role="tablist" aria-label="Sections">
              <button role="tab" type="button" data-tab="devices" aria-selected="true">Appareils</button>
              <button role="tab" type="button" data-tab="code" aria-selected="false">Code et protections</button>
              <button role="tab" type="button" data-tab="journal" aria-selected="false">Journal</button>
            </nav>
          </div>
        </header>
        <div class="scroll" id="scroll">
          <main class="gutter" id="main"></main>
        </div>
        <div class="savebar gutter" id="savebar" hidden>
          <div class="in">
            <p id="changes" role="status"></p>
            <button class="btn" type="button" id="cancel">Annuler</button>
            <button class="btn primary" type="button" id="save">Enregistrer</button>
          </div>
          <p class="error" id="save-error" role="alert" hidden></p>
        </div>
        <div class="toast" id="toast" role="status" hidden></div>
        <dialog class="sheet" id="aliases" aria-labelledby="aliases-title"></dialog>
      </div>`;
    const root = this.shadowRoot;
    root.getElementById("menu").addEventListener("click", () => {
      this.dispatchEvent(new Event("hass-toggle-menu", { bubbles: true, composed: true }));
    });
    root.querySelector("nav").addEventListener("click", (ev) => {
      const button = ev.target.closest("[data-tab]");
      if (button) this._showTab(button.dataset.tab);
    });
    root.getElementById("cancel").addEventListener("click", () => this._cancel());
    root.getElementById("save").addEventListener("click", () => this._save());
    const main = root.getElementById("main");
    main.addEventListener("click", (ev) => this._onClick(ev));
    main.addEventListener("change", (ev) => this._onChange(ev));
    main.addEventListener("input", (ev) => this._onInput(ev));
    const dialog = root.getElementById("aliases");
    dialog.addEventListener("click", (ev) => this._onAliasClick(ev));
    dialog.addEventListener("input", (ev) => {
      if (ev.target.id === "alias-input" && this._alias) {
        this._alias.input = ev.target.value;
        if (this._alias.error) this._setAliasError("");
      }
    });
    dialog.addEventListener("submit", (ev) => {
      ev.preventDefault();
      this._addAlias();
    });
    dialog.addEventListener("close", () => {
      this._alias = null;
    });
    this._renderAll();
  }

  _showTab(tab) {
    this._tab = tab;
    this._renderAll();
    this.shadowRoot.getElementById("scroll").scrollTop = 0;
    if (tab === "journal") this._loadJournal();
    if (tab === "code") this._refreshState();
  }

  // --- Affichage ----------------------------------------------------------------------------

  _renderAll() {
    if (!this._built) return;
    const root = this.shadowRoot;
    for (const button of root.querySelectorAll("nav [data-tab]")) {
      button.setAttribute("aria-selected", String(button.dataset.tab === this._tab));
    }
    const main = root.getElementById("main");
    if (this._error && !this._data) {
      main.innerHTML = `<div class="banner err" role="alert"><p>${esc(this._error)}</p>
        <button class="btn small" type="button" data-act="retry">Réessayer</button></div>`;
    } else if (!this._data) {
      main.innerHTML = `<p class="hint note">Chargement…</p>`;
    } else if (this._tab === "devices") {
      main.innerHTML = this._devicesView();
      this._renderList();
    } else if (this._tab === "code") {
      main.innerHTML = this._codeView();
    } else {
      main.innerHTML = this._journalView();
    }
    this._renderLive();
    this._renderSavebar();
  }

  /** Ce qui suit Home Assistant en direct : liaison, accès, bouton du menu. */
  _renderLive() {
    if (!this._built) return;
    const root = this.shadowRoot;
    const hass = this._hass;
    root.getElementById("menu").hidden = !(
      this._narrow || (hass && hass.dockedSidebar === "always_hidden")
    );
    const link = root.getElementById("link");
    if (!this._data) {
      link.innerHTML = "";
      return;
    }
    const [kind, text] = this._linkState();
    link.innerHTML = `<span class="dot ${kind}" aria-hidden="true"></span><span>${esc(text)}</span>`;
    const access = root.getElementById("access");
    if (access) access.checked = this._enabled();
    // La liaison ou l'accès ont changé : l'état du verrou et la raison d'un arrêt aussi, peut-être.
    const key = `${kind}|${this._enabled()}`;
    if (this._liveKey && key !== this._liveKey) this._refreshState();
    this._liveKey = key;
  }

  _entityState(entityId) {
    const states = this._hass && this._hass.states;
    return entityId && states ? states[entityId] : undefined;
  }

  _enabled() {
    const state = this._entityState(this._data.link.switch);
    return state ? state.state === "on" : this._data.link.enabled;
  }

  _linkState() {
    const link = this._data.link;
    if (!this._enabled()) return ["", "Accès coupé"];
    const sensor = this._entityState(link.sensor);
    const connected = sensor ? sensor.state === "on" : link.connected;
    if (connected) return ["on", "Relié à Oscar"];
    if (link.stopped === "unlinked") return ["bad", "Non reliée : nouveau code nécessaire"];
    if (link.stopped === "protocol") return ["bad", "Mise à jour nécessaire"];
    return ["wait", "Hors ligne"];
  }

  _serviceBanner() {
    const service = this._data.link.custom_service;
    return service
      ? `<div class="banner err" role="status"><p>Cette maison n’est pas reliée au service de Folonia, mais à ${esc(service)}. Si vous n’êtes pas à l’origine de ce réglage, supprimez l’intégration.</p></div>`
      : "";
  }

  _secretBanner() {
    if (!this._data.secret_needed) return "";
    const action =
      this._tab === "code"
        ? ""
        : `<button class="btn small" type="button" data-act="to-code">Choisir un code</button>`;
    return `<div class="banner" role="status"><p>Un appareil partagé est sous protection et aucun code ni mot de passe n’est réglé : d’ici là, Oscar refuse ce qui demande un code. Choisissez un code ou un mot de passe, décochez la protection, ou laissez l’appareil sans code.</p>${action}</div>`;
  }

  _devicesView() {
    const data = this._data;
    const hasSwitch = Boolean(data.link.switch);
    const top = `${this._serviceBanner()}${this._secretBanner()}
      <div class="card pad">
        <div class="access">
          <div>
            <h2>Accès d’Oscar</h2>
            <p>Coupé, Oscar ne voit et ne commande plus rien, sans rien perdre de vos réglages.</p>
          </div>
          ${toggle('id="access"', this._enabled(), !hasSwitch, "Accès d’Oscar")}
        </div>
        <div class="summary" id="summary"></div>
        <p class="advice" id="over" hidden></p>
      </div>`;
    if (!data.devices.length) {
      return `${top}
        <div class="card"><div class="empty">
          <p>Aucun appareil n’est exposé aux assistants vocaux. Exposez d’abord ceux qu’Oscar pourra lire ou commander, puis revenez ici.</p>
          <a href="${EXPOSE_URL}">Exposer des appareils aux assistants vocaux</a>
        </div></div>`;
    }
    const areas = [...new Set(data.devices.map((d) => d.area).filter(Boolean))].sort((a, b) =>
      a.localeCompare(b, "fr"),
    );
    const noArea = data.devices.some((d) => !d.area);
    if (this._area && this._area !== "-" && !areas.includes(this._area)) this._area = "";
    const option = (value, label) =>
      `<option value="${esc(value)}" ${this._area === value ? "selected" : ""}>${esc(label)}</option>`;
    const sortOption = (value, label) =>
      `<option value="${value}" ${this._sort === value ? "selected" : ""}>${label}</option>`;
    return `${top}
      <div class="card">
        <div class="tools">
          <label class="search">${SEARCH_ICON}
            <input id="query" type="search" placeholder="Appareil, pièce, type…" autocomplete="off" aria-label="Chercher" value="${esc(this._query)}">
          </label>
          <div class="chips" role="group" aria-label="Filtre">
            ${FILTERS.map(
              ([value, label]) =>
                `<button class="chip" type="button" data-filter="${value}" aria-pressed="${this._filter === value}">${label}</button>`,
            ).join("")}
          </div>
          <div class="row-tools">
            <select id="area" aria-label="Pièce">
              ${option("", "Toutes les pièces")}
              ${areas.map((a) => option(a, a)).join("")}
              ${noArea ? option("-", "Sans pièce") : ""}
            </select>
            <select id="sort" aria-label="Trier">
              ${sortOption("area", "Par pièce")}${sortOption("name", "Par nom")}${sortOption("kind", "Par type")}
            </select>
            <span class="count" id="count"></span>
          </div>
        </div>
        <div class="head" aria-hidden="true"><span>Appareil</span><span>Lire</span><span>Commander</span><span>Sans code</span></div>
        <div class="list" id="list" role="list"></div>
        <p class="hint foot">Seuls les appareils exposés aux assistants vocaux apparaissent ici ; retirer l’exposition les retire aussi à Oscar. <a href="${EXPOSE_URL}">Exposer d’autres appareils</a></p>
      </div>`;
  }

  _visibleDevices() {
    const query = this._query.trim().toLocaleLowerCase("fr");
    const rows = this._data.devices.filter((d) => {
      const choice = this._choiceOf(d);
      if (this._area === "-" ? d.area : this._area && d.area !== this._area) return false;
      if (this._filter === "shared" && !(choice.read || choice.control)) return false;
      if (this._filter === "sensitive" && !d.sensitive) return false;
      if (this._filter === "exempt" && !choice.exempt) return false;
      if (!query) return true;
      const aliases = [...(d.aliases || []), ...(d.area_aliases || [])].join(" ");
      return `${d.name} ${d.area || ""} ${aliases} ${d.kind} ${d.entity_id}`
        .toLocaleLowerCase("fr")
        .includes(query);
    });
    const name = (d) => d.name || d.entity_id;
    const area = (d) => d.area || "￿";
    const keys = {
      area: (a, b) => area(a).localeCompare(area(b), "fr") || name(a).localeCompare(name(b), "fr"),
      name: (a, b) => name(a).localeCompare(name(b), "fr"),
      kind: (a, b) => a.kind.localeCompare(b.kind, "fr") || name(a).localeCompare(name(b), "fr"),
    };
    return rows.sort(keys[this._sort]);
  }

  _row(d) {
    const choice = this._choiceOf(d);
    const shared = choice.read || choice.control;
    const id = esc(d.entity_id);
    const name = d.name || d.entity_id;
    const details = [d.area || "Sans pièce", d.kind, d.state].filter(Boolean).map(esc).join(" · ");
    const dash = '<span aria-hidden="true">—</span>';
    const aliases = d.aliases || [];
    const aka = aliases.length
      ? `<small class="aka">Alias : ${aliases.map(esc).join(", ")}</small>`
      : "";
    const names = `<span class="title"><b title="${id}">${esc(name)}</b>${
      d.aliases_editable ? PEN_ICON : ""
    }</span>${aka}<small>${details}${d.sensitive ? ' · <span class="warn">⚠ sensible</span>' : ""}</small>`;
    // Un appareil au registre des entités : toucher son nom ouvre ses alias.
    const who = d.aliases_editable
      ? `<button class="names" type="button" data-act="aliases" data-id="${id}" aria-haspopup="dialog">${names}<span class="vh">, modifier les alias</span></button>`
      : `<span class="names">${names}</span>`;
    return `<div class="item" role="listitem">
      <div class="who">
        <span class="ico${d.sensitive ? " sens" : ""}">${svg(iconFor(d))}</span>
        ${who}
      </div>
      <span class="cell">${toggle(`data-id="${id}" data-field="read"`, shared, choice.control, `Lire : ${name}`)}</span>
      <span class="cell">${
        d.controllable
          ? toggle(`data-id="${id}" data-field="control"`, choice.control, false, `Commander : ${name}`)
          : dash
      }</span>
      <span class="cell">${
        d.protectable
          ? toggle(`data-id="${id}" data-field="exempt"`, choice.exempt, !shared, `Sans code : ${name}`)
          : dash
      }</span>
    </div>`;
  }

  _renderList() {
    const root = this.shadowRoot;
    const list = root.getElementById("list");
    this._renderSummary();
    if (!list) return;
    const focused = root.activeElement;
    const refocus =
      focused && focused.dataset && focused.dataset.id
        ? [focused.dataset.id, focused.dataset.field]
        : null;
    const rows = this._visibleDevices();
    root.getElementById("count").textContent = `${rows.length} sur ${this._data.devices.length}`;
    list.innerHTML = rows.length
      ? rows.map((d) => this._row(d)).join("")
      : `<div class="empty"><p>Aucun appareil ne correspond. Effacez la recherche ou changez de filtre.</p></div>`;
    if (refocus) {
      const again = list.querySelector(
        `[data-id="${CSS.escape(refocus[0])}"][data-field="${refocus[1]}"]`,
      );
      if (again) again.focus();
    }
  }

  _renderSummary() {
    const root = this.shadowRoot;
    const summary = root.getElementById("summary");
    if (!summary) return;
    let shared = 0;
    let control = 0;
    let exempt = 0;
    for (const d of this._data.devices) {
      const choice = this._choiceOf(d);
      if (choice.read || choice.control) shared += 1;
      if (choice.control) control += 1;
      if (choice.exempt) exempt += 1;
    }
    summary.innerHTML = [
      [shared, shared > 1 ? "partagés" : "partagé"],
      [control, control > 1 ? "commandés" : "commandé"],
      [exempt, "sans code"],
    ]
      .map(([n, label]) => `<div class="stat"><b>${n}</b><span>${label}</span></div>`)
      .join("");
    const over = root.getElementById("over");
    const max = this._data.max_shared;
    over.hidden = !(max && shared > max);
    over.textContent = `Plus de ${max} appareils partagés : Oscar n’en voit que ${max}. Partagez-en moins.`;
  }

  _secretField(key, label, set, inputAttrs, hint) {
    const clearing = this._clear[key];
    const badge = clearing
      ? '<span class="badge clear">sera effacé</span>'
      : set
        ? '<span class="badge set">✓ réglé</span>'
        : '<span class="badge">aucun</span>';
    const action = clearing
      ? `<button class="btn small" type="button" data-act="keep" data-key="${key}">Garder</button>`
      : set
        ? `<button class="btn small" type="button" data-act="clear" data-key="${key}">Effacer</button>`
        : "";
    const error = this._fieldErrors[key];
    const advice = key === "phrase" && this._advice ? `<p class="advice">${esc(this._advice)}</p>` : "";
    return `<div class="field">
      <div class="field-head"><label for="secret-${key}">${label}</label>${badge}</div>
      <div class="input-row">
        <input id="secret-${key}" data-secret="${key}" ${inputAttrs} value="${esc(this._draft[key])}" ${
          clearing ? "disabled" : ""
        } aria-invalid="${Boolean(error)}" autocomplete="off" spellcheck="false">
        ${action}
      </div>
      ${error ? `<p class="error" role="alert">${esc(error)}</p>` : ""}
      ${advice}
      <p class="hint">${hint}</p>
    </div>`;
  }

  _codeView() {
    const data = this._data;
    const lockOpen = this._protection("lock_open");
    const lockRead = this._protection("lock_read");
    const lock = data.lock;
    let lockLine;
    if (lock.locked) {
      lockLine = `<span class="dot bad" aria-hidden="true"></span><p><b>Bloqué</b> : ${lock.max_failures} essais faux en vingt-quatre heures. Oscar ne fait plus rien de ce qui est sous code. Pour débloquer, éteignez puis rallumez « Accès d’Oscar », ou enregistrez un nouveau code ou mot de passe.</p>`;
    } else if (lock.failures) {
      lockLine = `<span class="dot wait" aria-hidden="true"></span><p><b>Ouvert</b> : ${plural(
        lock.failures,
        "essai faux",
        "essais faux",
      )} sur ${lock.max_failures} ces dernières vingt-quatre heures.</p>`;
    } else {
      lockLine = `<span class="dot on" aria-hidden="true"></span><p><b>Ouvert</b> : aucun essai faux ces dernières vingt-quatre heures.</p>`;
    }
    const general = this._fieldErrors.general
      ? `<div class="banner err" role="alert"><p>${esc(this._fieldErrors.general)}</p></div>`
      : "";
    const blocked = lock.locked
      ? `<div class="banner err" role="status"><p>Verrou vocal bloqué : ${lock.max_failures} essais faux en vingt-quatre heures. Pour débloquer, éteignez puis rallumez « Accès d’Oscar », ou enregistrez un nouveau code ou mot de passe.</p></div>`
      : "";
    return `${blocked}${this._secretBanner()}${general}
      <div class="card pad">
        <h2>Vos secrets</h2>
        <p class="hint">Deux secrets possibles, l’un ou l’autre suffit. Ils sont vérifiés ici : Folonia ne les garde pas, seule leur empreinte est gardée dans Home Assistant. Laissez un champ vide pour garder ce qui est réglé.</p>
        ${this._secretField(
          "code",
          "Code chiffré",
          data.secrets.code,
          'type="password" inputmode="numeric" placeholder="Nouveau code (4 à 8 chiffres)"',
          "Dit à voix haute, ou tapé sur le clavier du téléphone (puis dièse) si vous n’êtes pas seul.",
        )}
        ${this._secretField(
          "phrase",
          "Mot de passe parlé",
          data.secrets.phrase,
          'type="text" placeholder="Par exemple : dragon rouge" autocapitalize="off"',
          "Un mot ou une courte phrase, dit à voix haute. Majuscules, accents et ponctuation ne comptent pas. Au moins quatre lettres ; six lettres ou deux mots sont conseillés.",
        )}
      </div>
      <div class="card pad">
        <h2>Quand demander le code</h2>
        <p class="hint">Par défaut, Oscar demande votre code ou votre mot de passe avant d’ouvrir la maison, et avant de dire ce qui révèle qu’elle est vide. Chaque protection se décoche, en connaissance de cause. Le code ne couvre que les appareils que Home Assistant déclare comme serrure, alarme, portail ou porte : un portail commandé par un interrupteur ou un script n’est pas protégé. Un code accepté vaut jusqu’à la fin de l’appel.</p>
        <div class="opt">
          <div><b>Pour déverrouiller, désarmer, ouvrir</b><p>Serrures, alarme, portail et porte de garage ne s’ouvrent qu’avec votre code ou votre mot de passe.</p></div>
          ${toggle('data-prot="lock_open"', lockOpen, false, "Code pour déverrouiller, désarmer, ouvrir")}
        </div>
        ${
          lockOpen
            ? ""
            : `<div class="warnbox" role="status">Décoché : quiconque appelle depuis votre numéro peut demander à Oscar de déverrouiller, de désarmer ou d’ouvrir.</div>`
        }
        <div class="opt">
          <div><b>Pour connaître l’état des appareils sensibles</b><p>Présence, serrures, alarme, portes et fenêtres (marqués ⚠) disent quand votre maison est vide.</p></div>
          ${toggle('data-prot="lock_read"', lockRead, false, "Code pour lire les appareils sensibles")}
        </div>
        ${
          lockRead
            ? ""
            : `<div class="warnbox" role="status">Décoché : Oscar dit l’état de ces appareils à quiconque appelle depuis votre numéro.</div>`
        }
        <p class="hint">Verrouiller, armer une alarme désarmée, fermer et arrêter ne demandent jamais de code. Les appareils marqués « Sans code » dans la liste n’en demandent jamais.</p>
      </div>
      <div class="card pad">
        <h2>Verrou vocal</h2>
        <div class="lockstate">${lockLine}</div>
        <p class="hint">Cinq essais faux en vingt-quatre heures, code et mot de passe ensemble, dits ou tapés, bloquent le verrou ; Home Assistant vous prévient.</p>
      </div>`;
  }

  _journalView() {
    const entries = this._journal;
    let body;
    if (entries === null) {
      body = `<p class="hint pad">Chargement…</p>`;
    } else if (typeof entries === "string") {
      body = `<div class="pad"><p class="error">${esc(entries)}</p></div>`;
    } else if (!entries.length) {
      body = `<p class="hint pad">Rien pour l’instant : Oscar n’a encore rien lu ni commandé depuis le démarrage de Home Assistant.</p>`;
    } else {
      body = `<ul class="log">${entries
        .map((line) => {
          const [time, full] = this._time(line.time);
          const who = line.name ? `<small>${esc(line.name)}</small>` : "";
          return `<li><time datetime="${esc(line.time)}" title="${esc(full)}">${esc(time)}</time><span><span class="${
            line.refused ? "bad" : ""
          }">${esc(capitalize(line.message))}</span>${who}</span></li>`;
        })
        .join("")}</ul>`;
    }
    return `<div class="row-actions note">
        <p class="hint">Les dernières lignes depuis le démarrage de Home Assistant, les plus récentes d’abord. Tout est aussi au <a href="${LOGBOOK_URL}">journal de bord</a>.</p>
        <button class="btn small" type="button" data-act="journal">Actualiser</button>
      </div>
      <div class="card">${body}</div>`;
  }

  _time(iso) {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return [iso, iso];
    const now = new Date();
    const hm = date.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
    const full = date.toLocaleString("fr-FR");
    if (date.toDateString() === now.toDateString()) return [hm, full];
    return [`${date.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" })} ${hm}`, full];
  }

  _renderSavebar() {
    if (!this._built) return;
    const root = this.shadowRoot;
    const count = this._changeCount();
    root.getElementById("savebar").hidden = count === 0 && !this._saveError;
    root.getElementById("changes").textContent =
      count === 0
        ? ""
        : count === 1
          ? "1 changement non enregistré"
          : `${count} changements non enregistrés`;
    root.getElementById("save").disabled = this._busy || count === 0;
    root.getElementById("cancel").disabled = this._busy;
    root.getElementById("save").textContent = this._busy ? "Enregistrement…" : "Enregistrer";
    const error = root.getElementById("save-error");
    error.hidden = !this._saveError;
    error.textContent = this._saveError;
  }

  _toast(text) {
    const toast = this.shadowRoot.getElementById("toast");
    toast.textContent = text;
    toast.hidden = false;
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => {
      toast.hidden = true;
    }, 1800);
  }

  // --- Gestes -------------------------------------------------------------------------------

  _onClick(ev) {
    const chip = ev.target.closest("[data-filter]");
    if (chip) {
      this._filter = chip.dataset.filter;
      for (const c of this.shadowRoot.querySelectorAll("[data-filter]")) {
        c.setAttribute("aria-pressed", String(c === chip));
      }
      this._renderList();
      return;
    }
    const button = ev.target.closest("[data-act]");
    if (!button) return;
    const act = button.dataset.act;
    if (act === "retry") {
      this._error = null;
      this._renderAll();
      this._load();
    } else if (act === "to-code") {
      this._showTab("code");
    } else if (act === "aliases") {
      this._openAliases(button.dataset.id);
    } else if (act === "journal") {
      this._loadJournal();
    } else if (act === "clear" || act === "keep") {
      const key = button.dataset.key;
      this._clear[key] = act === "clear";
      this._draft[key] = "";
      delete this._fieldErrors[key];
      delete this._fieldErrors.general;
      this._renderAll();
    }
  }

  _onChange(ev) {
    const target = ev.target;
    if (target.id === "access") {
      this._setAccess(target.checked);
    } else if (target.dataset.field) {
      this._choose(target.dataset.id, target.dataset.field, target.checked);
    } else if (target.dataset.prot) {
      const key = target.dataset.prot;
      if (target.checked === this._data.protections[key]) delete this._prot[key];
      else this._prot[key] = target.checked;
      this._saveError = "";
      this._renderAll();
    } else if (target.id === "area" || target.id === "sort") {
      this[`_${target.id}`] = target.value;
      this._renderList();
    }
  }

  _onInput(ev) {
    const target = ev.target;
    if (target.id === "query") {
      this._query = target.value;
      this._renderList();
    } else if (target.dataset.secret) {
      const key = target.dataset.secret;
      this._draft[key] = target.value;
      if (this._fieldErrors[key]) {
        delete this._fieldErrors[key];
        target.setAttribute("aria-invalid", "false");
        const error = target.closest(".field").querySelector(".error");
        if (error) error.remove();
      }
      this._renderSavebar();
    }
  }

  /** Commander rend lisible ; plus partagé, plus d'exemption. Les règles sont refaites au serveur. */
  _choose(entityId, field, on) {
    const device = this._byId.get(entityId);
    if (!device) return;
    const next = { ...this._choiceOf(device), [field]: on };
    if (field === "control" && on) next.read = true;
    if (field === "read" && !on) next.control = false;
    if (!(next.read || next.control) || !device.protectable) next.exempt = false;
    if (!device.controllable) next.control = false;
    const saved = this._savedOf(device);
    if (FIELDS.every((f) => next[f] === saved[f])) this._changes.delete(entityId);
    else this._changes.set(entityId, next);
    this._saveError = "";
    this._renderList();
    this._renderSavebar();
  }

  // --- Alias d'Assist ------------------------------------------------------------------------

  _openAliases(entityId) {
    const device = this._byId.get(entityId);
    if (!device || !device.aliases_editable) return;
    this._alias = { id: entityId, list: [...(device.aliases || [])], input: "", error: "", busy: false };
    this._renderAliases();
    const dialog = this.shadowRoot.getElementById("aliases");
    // Le clavier du téléphone ne s'ouvre pas d'office : on peut venir seulement retirer.
    if (!dialog.open) dialog.showModal();
  }

  _renderAliases() {
    const edit = this._alias;
    const dialog = this.shadowRoot.getElementById("aliases");
    const device = edit && this._byId.get(edit.id);
    if (!device) {
      if (dialog.open) dialog.close();
      return;
    }
    const name = device.name || device.entity_id;
    const pills = edit.list.length
      ? `<ul class="pills" aria-label="Alias de ${esc(name)}">${edit.list
          .map(
            (alias, index) =>
              `<li class="pill"><span>${esc(alias)}</span><button type="button" data-act="alias-remove" data-index="${index}" aria-label="Retirer ${esc(alias)}">×</button></li>`,
          )
          .join("")}</ul>`
      : `<p class="hint">Aucun alias pour l’instant.</p>`;
    const full = edit.list.length >= MAX_ALIASES;
    let area = "";
    if (device.area) {
      const link = device.area_id
        ? `${AREAS_URL}/area/${encodeURIComponent(device.area_id)}`
        : `${AREAS_URL}/dashboard`;
      const known = (device.area_aliases || []).map(esc).join(", ");
      area = `<p class="area-al">Pièce « ${esc(device.area)} » : ${
        known ? `aussi ${known}` : "aucun alias"
      }. Ils se modifient dans <a href="${link}">les réglages de la pièce</a>.</p>`;
    }
    // Le focus va à la fenêtre elle-même, pas au premier bouton : pas d'anneau sur « Fermer ».
    dialog.innerHTML = `<div class="sheet-in" tabindex="-1" autofocus>
      <div class="sheet-head">
        <div><h2 id="aliases-title">Alias</h2><p>${esc(name)}${device.area ? ` · ${esc(device.area)}` : ""}</p></div>
        <button class="x" type="button" data-act="alias-close" aria-label="Fermer">×</button>
      </div>
      <p class="hint">D’autres noms pour cet appareil : Oscar le reconnaît aussi sous ces noms. Ce sont les alias d’Assist : les modifier ici les modifie aussi pour Assist.</p>
      ${pills}
      <form class="input-row" id="alias-form">
        <input id="alias-input" type="text" maxlength="${MAX_ALIAS}" placeholder="${
          full ? `${MAX_ALIASES} alias au plus` : "Nouvel alias, par exemple : le portillon"
        }" value="${esc(edit.input)}" aria-label="Nouvel alias" autocomplete="off" enterkeyhint="done" ${
          full || edit.busy ? "disabled" : ""
        }>
        <button class="btn small" type="submit" ${full || edit.busy ? "disabled" : ""}>Ajouter</button>
      </form>
      <p class="error" id="alias-error" role="alert" ${edit.error ? "" : "hidden"}>${esc(edit.error)}</p>
      ${area}
      <div class="sheet-actions">
        <button class="btn" type="button" data-act="alias-close">Annuler</button>
        <button class="btn primary" type="button" data-act="alias-save" ${edit.busy ? "disabled" : ""}>${
          edit.busy ? "Enregistrement…" : "Enregistrer"
        }</button>
      </div>
    </div>`;
  }

  _setAliasError(text) {
    this._alias.error = text;
    const error = this.shadowRoot.getElementById("alias-error");
    if (!error) return;
    error.textContent = text;
    error.hidden = !text;
  }

  /** Ajoute la saisie à la liste ; `false` si elle est refusée (et dit pourquoi). */
  _addAlias() {
    const edit = this._alias;
    if (!edit || edit.busy) return false;
    const alias = cleanAlias(edit.input);
    if (!alias) return true;
    const device = this._byId.get(edit.id);
    const key = alias.toLocaleLowerCase("fr");
    let error = "";
    if (edit.list.some((a) => a.toLocaleLowerCase("fr") === key)) error = "Cet alias est déjà dans la liste.";
    else if ((device.name || "").toLocaleLowerCase("fr") === key) error = "C’est déjà le nom de l’appareil.";
    else if (edit.list.length >= MAX_ALIASES) error = `${MAX_ALIASES} alias au plus.`;
    if (error) {
      this._setAliasError(error);
      return false;
    }
    edit.list.push(alias);
    edit.input = "";
    edit.error = "";
    this._renderAliases();
    const input = this.shadowRoot.getElementById("alias-input");
    if (!input.disabled) input.focus();
    return true;
  }

  _onAliasClick(ev) {
    const dialog = this.shadowRoot.getElementById("aliases");
    // Un geste sur le fond, hors de la fenêtre : fermer, sans rien enregistrer.
    if (ev.target === dialog) {
      dialog.close();
      return;
    }
    const button = ev.target.closest("[data-act]");
    if (!button || !this._alias) return;
    const act = button.dataset.act;
    if (act === "alias-close") {
      dialog.close();
    } else if (act === "alias-remove") {
      const index = Number(button.dataset.index);
      this._alias.list.splice(index, 1);
      this._alias.error = "";
      this._renderAliases();
      // Le focus passe à l'alias voisin, ou à défaut au bouton Fermer.
      const pills = dialog.querySelectorAll("[data-act='alias-remove']");
      (pills[Math.min(index, pills.length - 1)] || dialog.querySelector(".x")).focus();
    } else if (act === "alias-save") {
      this._saveAliases();
    }
  }

  /** Une saisie en attente est ajoutée d'abord ; l'intégration recoupe et enregistre. */
  async _saveAliases() {
    const edit = this._alias;
    if (!edit || edit.busy || !this._addAlias()) return;
    edit.busy = true;
    this._renderAliases();
    try {
      const result = await this._hass.callWS({
        type: "folonia/aliases",
        entity_id: edit.id,
        aliases: edit.list,
      });
      this._ingest(result);
      this.shadowRoot.getElementById("aliases").close();
      if (this._tab === "devices") this._renderList();
      this._toast("Alias enregistrés");
    } catch (err) {
      if (this._alias !== edit) return;
      edit.busy = false;
      edit.error = this._message(err);
      this._renderAliases();
    }
  }

  async _setAccess(on) {
    const entityId = this._data.link.switch;
    if (!entityId) return;
    try {
      await this._hass.callService("switch", on ? "turn_on" : "turn_off", { entity_id: entityId });
    } catch (err) {
      this._toast(this._message(err));
      this._renderLive();
    }
  }

  _cancel() {
    this._changes.clear();
    this._prot = {};
    this._draft = { code: "", phrase: "" };
    this._clear = { code: false, phrase: false };
    this._fieldErrors = {};
    this._saveError = "";
    this._advice = "";
    this._renderAll();
  }

  /** Les secrets réglés d'abord, puis les choix, puis les effacements : un secret effacé
   * n'est refusé que s'il protège encore quelque chose une fois les choix enregistrés. */
  async _save() {
    if (this._busy || !this._data) return;
    this._busy = true;
    this._saveError = "";
    this._fieldErrors = {};
    this._advice = "";
    this._renderSavebar();
    const sets = {};
    for (const key of ["code", "phrase"]) if (this._draft[key]) sets[key] = this._draft[key];
    const clears = {};
    for (const key of ["code", "phrase"]) if (this._clear[key]) clears[key] = null;
    let step = "set";
    try {
      if (Object.keys(sets).length) {
        const result = await this._hass.callWS({ type: "folonia/secret", ...sets });
        this._ingest(result);
        this._draft = { code: "", phrase: "" };
        if (result.weak_phrase) {
          this._advice =
            "Mot de passe enregistré. Conseil : six lettres au moins, ou deux mots, le rendent plus difficile à deviner.";
        }
      }
      step = "save";
      if (this._changes.size || Object.keys(this._prot).length) {
        const lists = { read: [], control: [], exempt: [] };
        for (const d of this._data.devices) {
          const choice = this._choiceOf(d);
          for (const f of FIELDS) if (choice[f]) lists[f].push(d.entity_id);
        }
        const message = { type: "folonia/save", ...lists };
        for (const key of ["lock_open", "lock_read"]) message[key] = this._protection(key);
        const result = await this._hass.callWS(message);
        this._changes.clear();
        this._prot = {};
        this._ingest(result);
      }
      step = "clear";
      if (Object.keys(clears).length) {
        this._ingest(await this._hass.callWS({ type: "folonia/secret", ...clears }));
        this._clear = { code: false, phrase: false };
      }
      this._busy = false;
      this._renderAll();
      this._toast("Enregistré");
    } catch (err) {
      this._busy = false;
      const code = err && err.code;
      const message = this._message(err);
      if (code === "invalid_lock_code" || code === "invalid_lock_phrase") {
        // Le secret saisi est refusé avant tout le reste : rien n'est enregistré.
        this._fieldErrors[code === "invalid_lock_code" ? "code" : "phrase"] = message;
        this._saveError = "Rien n’est enregistré : corrigez le champ signalé dans « Code et protections ».";
        this._tab = "code";
      } else if (code === "lock_code_required") {
        // Les choix sont enregistrés ; seul l'effacement est refusé.
        this._fieldErrors.general = message;
        this._saveError = "Enregistré, sauf l’effacement du secret : voyez « Code et protections ».";
        this._tab = "code";
      } else {
        this._saveError = `${step === "set" ? "Rien n’est enregistré" : "L’enregistrement n’a pas abouti en entier"} : ${message}`;
      }
      this._renderAll();
    }
  }

  async _loadJournal() {
    if (!this._hass) return;
    try {
      const result = await this._hass.callWS({ type: "folonia/journal" });
      this._journal = result.entries;
    } catch (err) {
      this._journal = this._message(err);
    }
    if (this._tab === "journal") this._renderAll();
  }

  /** La liaison, l'accès, le verrou et les secrets, relus sans toucher aux choix en cours. */
  async _refreshState() {
    if (!this._hass || !this._data || this._refreshing) return;
    this._refreshing = true;
    try {
      const fresh = await this._hass.callWS({ type: "folonia/settings" });
      Object.assign(this._data, {
        link: fresh.link,
        lock: fresh.lock,
        secrets: fresh.secrets,
        secret_needed: fresh.secret_needed,
      });
      if (this._tab === "code" && !this._focusedInMain()) this._renderAll();
      else this._renderLive();
    } catch (_err) {
      // L'état reste celui de la dernière lecture.
    }
    this._refreshing = false;
  }

  _focusedInMain() {
    const focused = this.shadowRoot.activeElement;
    return Boolean(focused && focused.closest && focused.closest("main"));
  }
}

if (!customElements.get(TAG)) customElements.define(TAG, FoloniaPanel);

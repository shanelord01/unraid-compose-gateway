/**
 * unraid-compose-gateway dashboard tab.
 *
 * Plain IIFE, no build step. Uses window.__HERMES_PLUGIN_SDK__ for React and
 * hooks, and talks to the plugin backend at /api/plugins/ucg/.
 */
(function () {
  "use strict";

  var SDK = window.__HERMES_PLUGIN_SDK__ || {};
  var React = SDK.React;
  if (!React) {
    console.error("[ucg] Hermes plugin SDK not available");
    return;
  }
  var h = React.createElement;
  var hooks = SDK.hooks || SDK;
  var useState = hooks.useState;
  var useEffect = hooks.useEffect;
  var useCallback = hooks.useCallback;

  var BASE = "/api/plugins/ucg";

  function api(path, options) {
    if (typeof SDK.fetchJSON === "function") return SDK.fetchJSON(BASE + path, options);
    var fetcher = typeof SDK.authedFetch === "function" ? SDK.authedFetch : window.fetch;
    return fetcher(BASE + path, options).then(function (r) { return r.json(); });
  }

  var S = {
    page: { padding: "24px", maxWidth: "820px", margin: "0 auto" },
    h1: { fontSize: "20px", fontWeight: 600, marginBottom: "4px" },
    sub: { fontSize: "13px", opacity: 0.7, marginBottom: "20px" },
    card: { border: "1px solid rgba(128,128,128,0.25)", borderRadius: "10px",
            padding: "16px", marginBottom: "16px" },
    cardTitle: { fontSize: "15px", fontWeight: 600, marginBottom: "2px" },
    cardHint: { fontSize: "12px", opacity: 0.65, marginBottom: "14px" },
    label: { fontSize: "13px", marginBottom: "4px" },
    note: { fontSize: "11px", opacity: 0.6, marginTop: "4px" },
    input: { width: "100%", padding: "6px 8px", borderRadius: "6px",
             border: "1px solid rgba(128,128,128,0.35)", background: "transparent",
             color: "inherit", fontSize: "13px", fontFamily: "ui-monospace, monospace" },
    row: { display: "flex", alignItems: "center", gap: "8px", marginBottom: "12px" },
    badge: { fontSize: "10px", padding: "1px 6px", borderRadius: "999px",
             border: "1px solid rgba(128,128,128,0.4)", opacity: 0.8, marginLeft: "8px" },
    warnBadge: { fontSize: "10px", padding: "1px 6px", borderRadius: "999px",
                 border: "1px solid rgba(200,120,0,0.6)", color: "rgb(200,120,0)",
                 opacity: 0.9, marginLeft: "8px" },
    btn: { padding: "7px 14px", borderRadius: "7px", fontSize: "13px", cursor: "pointer",
           border: "1px solid rgba(128,128,128,0.35)", background: "transparent",
           color: "inherit", marginRight: "8px" },
    status: { fontSize: "12px", marginLeft: "4px", opacity: 0.85 },
    pill: { fontSize: "11px", padding: "2px 8px", borderRadius: "999px",
            border: "1px solid rgba(128,128,128,0.35)", marginRight: "6px",
            marginBottom: "6px", display: "inline-block" },
    excludedPill: { fontSize: "11px", padding: "2px 8px", borderRadius: "999px",
                    border: "1px solid rgba(200,60,60,0.5)", color: "rgb(200,60,60)",
                    marginRight: "6px", marginBottom: "6px", display: "inline-block" },
    a: { color: "inherit", textDecoration: "underline", opacity: 0.85 }
  };

  function Source(props) {
    if (!props.from || props.from === "settings") return null;
    return h("span", { style: S.badge }, props.from === "env" ? "from env" : "not set");
  }

  function App() {
    var a = useState(null); var st = a[0]; var setSt = a[1];
    var b = useState({}); var src = b[0]; var setSrc = b[1];
    var c = useState(""); var url = c[0]; var setUrl = c[1];
    var d = useState(""); var token = d[0]; var setToken = d[1];
    var e = useState(false); var allowWrites = e[0]; var setAllowWrites = e[1];
    var f = useState(30); var timeout_ = f[0]; var setTimeout_ = f[1];
    var g = useState(""); var msg = g[0]; var setMsg = g[1];
    var i = useState(null); var test = i[0]; var setTest = i[1];
    var j = useState(false); var busy = j[0]; var setBusy = j[1];
    var k = useState(600); var longTimeout_ = k[0]; var setLongTimeout_ = k[1];

    var load = useCallback(function () {
      api("/settings").then(function (r) {
        if (r && r.ok) {
          setSt(r.settings); setSrc(r.sources || {});
          setUrl(r.settings.gateway_url || "");
          setAllowWrites(!!r.settings.allow_writes);
          setTimeout_(r.settings.timeout_seconds || 30);
          setLongTimeout_(r.settings.long_timeout_seconds || 600);
        } else setMsg((r && r.error) || "failed to load settings");
      }).catch(function (err) { setMsg(String(err)); });
    }, []);

    useEffect(function () { load(); }, [load]);

    function save(then) {
      setBusy(true); setMsg("");
      var patch = {
        gateway_url: url,
        allow_writes: allowWrites,
        timeout_seconds: timeout_,
        long_timeout_seconds: longTimeout_
      };
      // Only send the token when the field has been typed into, so saving
      // other changes never clears a stored token.
      if (token) patch.gateway_token = token;
      api("/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch)
      }).then(function (r) {
        setBusy(false);
        if (r && r.ok) {
          setSt(r.settings); setSrc(r.sources || {}); setToken("");
          setMsg("Saved. Restart the Hermes gateway for tool registration changes to take effect.");
          if (then) then();
        } else setMsg((r && r.error) || "save failed");
      }).catch(function (err) { setBusy(false); setMsg(String(err)); });
    }

    function testIt() {
      setTest(null); setMsg("");
      api("/test").then(function (r) { setTest(r); })
        .catch(function (err) { setMsg(String(err)); });
    }

    if (!st) {
      return h("div", { style: S.page }, h("div", { style: S.sub }, msg || "Loading..."));
    }

    // The gateway's own per-command limit, once a connection test has read it.
    // Older gateways don't publish it; then we can only state the default.
    var gatewayLimit = (test && test.ok && test.whoami &&
                        typeof test.whoami.compose_timeout_seconds === "number")
      ? test.whoami.compose_timeout_seconds
      : null;

    return h("div", { style: S.page },
      h("div", { style: S.h1 }, "UCG"),
      h("div", { style: S.sub },
        "Connection to a running unraid-compose-gateway sidecar. Blank fields fall back to environment variables."),

      h("div", { style: S.card },
        h("div", { style: S.cardTitle }, "Connection"),

        h("div", { style: { marginBottom: "12px" } },
          h("div", { style: S.label }, "Gateway URL", h(Source, { from: src.gateway_url })),
          h("input", {
            type: "text", value: url, style: S.input,
            placeholder: "http://unraid-compose-gateway:8080",
            onChange: function (ev) { setUrl(ev.target.value); }
          })),

        h("div", { style: { marginBottom: "12px" } },
          h("div", { style: S.label }, "Gateway token",
            h("span", { style: S.badge }, st.gateway_token_set ? "stored" : "not set"),
            h(Source, { from: st.gateway_token_set ? src.gateway_token : null })),
          h("input", {
            type: "password", value: token, style: S.input,
            placeholder: st.gateway_token_set ? "stored - type to replace" : "the gateway's own GATEWAY_TOKEN",
            onChange: function (ev) { setToken(ev.target.value); }
          }),
          h("div", { style: S.note },
            "Never sent back to this page once saved; only whether one exists.")),

        h("div", { style: { display: "flex", gap: "18px", marginBottom: "12px" } },
          h("div", null,
            h("div", { style: S.label }, "Read timeout (seconds)", h(Source, { from: src.timeout_seconds })),
            h("input", {
              type: "number", min: "1", value: timeout_,
              style: Object.assign({}, S.input, { width: "110px" }),
              onChange: function (ev) { setTimeout_(parseInt(ev.target.value, 10) || 30); }
            }),
            h("div", { style: S.note }, "whoami, projects, status, logs")),
          h("div", null,
            h("div", { style: S.label }, "Action timeout (seconds)",
              h(Source, { from: src.long_timeout_seconds }),
              gatewayLimit && longTimeout_ <= gatewayLimit
                ? h("span", { style: S.warnBadge }, "too low")
                : null),
            h("input", {
              type: "number", min: "1", value: longTimeout_,
              style: Object.assign({}, S.input, { width: "110px" }),
              onChange: function (ev) { setLongTimeout_(parseInt(ev.target.value, 10) || 600); }
            }),
            h("div", { style: S.note }, "up, down, restart, pull, prune"))),

        h("div", { style: S.note },
          gatewayLimit
            ? (longTimeout_ <= gatewayLimit
                ? "This gateway gives a compose command up to " + gatewayLimit + "s. An action " +
                  "timeout of " + longTimeout_ + "s means this plugin gives up FIRST and reports " +
                  "failures for work the gateway goes on to finish. Set it above " + gatewayLimit + "s."
                : "This gateway gives a compose command up to " + gatewayLimit + "s, so the gateway " +
                  "is what decides an action failed - which is correct.")
            : "Keep the action timeout above the gateway's own COMPOSE_TIMEOUT_SECONDS (default 120) " +
              "so the gateway, not this plugin, decides when an action has failed. Run Test " +
              "connection to read the gateway's actual limit."),

        h("div", { style: S.row },
          h("input", {
            type: "checkbox", checked: allowWrites, id: "allow-writes",
            onChange: function (ev) { setAllowWrites(ev.target.checked); }
          }),
          h("label", { htmlFor: "allow-writes", style: S.label },
            "Allow compose control (restart / up / down / pull)"),
          h(Source, { from: src.allow_writes }),
          allowWrites ? null : h("span", { style: S.warnBadge }, "read-only")),
        h("div", { style: S.note },
          "The gateway's own ALLOWED_PROJECTS and SELF_EXCLUDE_PROJECTS are enforced " +
          "regardless of this setting - this only controls whether the agent will " +
          "attempt a mutating call at all. Changing it needs a Hermes gateway " +
          "restart to take effect, since tool registration happens at startup."),

        h("div", { style: { marginTop: "14px" } },
          h("button", { style: S.btn, disabled: busy,
                        onClick: function () { save(null); } }, busy ? "Saving..." : "Save"),
          h("button", { style: S.btn, onClick: testIt }, "Test connection"),
          msg ? h("span", { style: S.status }, msg) : null)),

      test ? h("div", { style: S.card },
        h("div", { style: S.cardTitle }, "Connection test"),
        test.ok
          ? h("div", null,
              h("div", { style: { fontSize: "13px", marginBottom: "10px" } },
                "Reached the gateway and it responded."),
              h("div", { style: S.label }, "Allowed projects"),
              h("div", { style: { marginBottom: "10px" } },
                (test.whoami.allowed_projects || []).length
                  ? test.whoami.allowed_projects.map(function (p) {
                      return h("span", { key: p, style: S.pill }, p);
                    })
                  : h("span", { style: S.note }, "none configured")),
              h("div", { style: S.label }, "Self-excluded (never mutated)"),
              h("div", { style: { marginBottom: "10px" } },
                (test.whoami.self_exclude_projects || []).length
                  ? test.whoami.self_exclude_projects.map(function (p) {
                      return h("span", { key: p, style: S.excludedPill }, p);
                    })
                  : h("span", { style: S.note }, "none")),
              h("div", { style: { fontSize: "12px" } },
                "Plugin update detection: " +
                (test.whoami.plugin_updates_enabled ? "enabled" : "disabled (no PLUGIN_DIR on the gateway)")),
              test.whoami.compose_version
                ? h("div", { style: { fontSize: "12px", marginTop: "4px" } },
                    "Compose version: " + test.whoami.compose_version +
                    " (" + (test.whoami.compose_version_source || "bundled") + ")" +
                    (test.whoami.host_compose_version
                      ? ", host reports " + test.whoami.host_compose_version
                      : ""))
                : null,
              gatewayLimit
                ? h("div", { style: { fontSize: "12px", marginTop: "4px" } },
                    "Gateway command limit: " + gatewayLimit + "s",
                    longTimeout_ <= gatewayLimit
                      ? h("span", { style: S.warnBadge },
                          "action timeout " + longTimeout_ + "s is lower")
                      : null)
                : h("div", { style: Object.assign({}, S.note, { marginTop: "4px" }) },
                    "This gateway does not publish compose_timeout_seconds - it predates that " +
                    "field. Assume its default of 120s."))
          : h("div", { style: { fontSize: "13px" } }, "Failed: " + (test.error || "unknown"))) : null);
  }

  if (window.__HERMES_PLUGINS__ && typeof window.__HERMES_PLUGINS__.register === "function") {
    window.__HERMES_PLUGINS__.register("ucg", App);
  } else {
    console.error("[ucg] window.__HERMES_PLUGINS__.register unavailable");
  }
})();

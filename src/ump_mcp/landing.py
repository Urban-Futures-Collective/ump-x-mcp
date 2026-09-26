"""A one-page browser view for people who open the server's address.

Everything else this service serves is for machines: /mcp speaks JSON-RPC and
answers a plain GET with a 401 challenge, /health answers with JSON. Someone
who pastes the hostname into a browser — a colleague, an admin checking the
deployment, a client developer — gets this instead of a 404: what the address
is, the endpoint to paste into a client, and what to expect when connecting.

It is deliberately self-contained: one HTML response plus the fonts and the
brand mark from the package, no CDN, no build step, no external request from
the visitor's browser. English and German, chosen from Accept-Language and
switchable with ?lang=.

Design: the Urban Futures Collective design system (claude.ai/design project
"Urban Futures Collective Design System", itself derived from
Urban-Futures-Collective/website-frontend). Its rules, followed here:
Poppins for headings and UI labels, Satoshi for body copy; yellow is the one
accent (borders, the heading underline, the focus ring); square corners on
every surface; thin quiet borders and a 1px shadow rather than glows; fluid
Utopia type and space scales; flat colour, no gradient except the signature
highlighter mark. Values below are copied from that project's tokens/*.css —
when it moves, move them with it.
"""

from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, Response
from starlette.routing import Route

from ump_mcp import __version__
from ump_mcp.config import Settings

LANGUAGES = ("en", "de")
DEFAULT_LANGUAGE = "en"

REPOSITORY_URL = "https://github.com/Urban-Futures-Collective/ump-x-mcp"
PLATFORM_URL = "https://ump-x.urbanfuturescollective.org/"
PROTOCOL_URL = "https://modelcontextprotocol.io"

_STATIC_DIR = __file__.rsplit("/", 1)[0] + "/static"
# Allow-list: the filename comes from the URL, so nothing else in the package
# directory (the licence file, the source next to it) is reachable.
_STATIC_FILES = {
    "poppins-400-latin.woff2": "font/woff2",
    "poppins-600-latin.woff2": "font/woff2",
    "Satoshi-Variable.woff2": "font/woff2",
    "ufc-mark.png": "image/png",
}

TEXT: dict[str, dict[str, str]] = {
    "en": {
        "org": "Urban Futures Collective",
        "title": "Urban Model Platform · MCP",
        # Split so the highlighter mark can sit on the middle phrase.
        "lede_before": "This address is a ",
        "lede_mark": "Model Context Protocol server",
        "lede_after": (
            ", not a website. Connected to an MCP client, the urban simulation "
            "models of the Urban Model Platform become tools an agent can run."
        ),
        "endpoint_label": "MCP endpoint",
        "copy": "Copy",
        "copied": "Copied",
        "steps_label": "Connecting",
        # Split so the platform name can carry the sign-up link.
        "step_1_before": "An account on the ",
        "step_1_link": "Urban Model Platform",
        "step_1_after": " is required — sign up there first.",
        "step_2": "Add the endpoint to an MCP client as a Streamable HTTP server.",
        "step_3": (
            "Sign in through the client — it opens Keycloak and keeps the session. "
            "No token to paste."
        ),
        "step_4": (
            "The account decides which models appear. Runs are asynchronous jobs: "
            "starting one returns a job ID, which the client polls."
        ),
        "source": "Source code",
        "platform": "Platform",
        "protocol": "About MCP",
        "health": "Health",
    },
    "de": {
        "org": "Urban Futures Collective",
        "title": "Urban Model Platform · MCP",
        "lede_before": "Diese Adresse ist ein ",
        "lede_mark": "Model-Context-Protocol-Server",
        "lede_after": (
            ", keine Webseite. In einem MCP-Client verbunden, werden die "
            "Stadtmodelle der Urban Model Platform zu Werkzeugen, die ein Agent "
            "rechnen kann."
        ),
        "endpoint_label": "MCP-Endpunkt",
        "copy": "Kopieren",
        "copied": "Kopiert",
        "steps_label": "Verbinden",
        "step_1_before": "Ein Konto auf der ",
        "step_1_link": "Urban Model Platform",
        "step_1_after": " ist erforderlich — dort zuerst registrieren.",
        "step_2": "Den Endpunkt in einem MCP-Client als Streamable-HTTP-Server eintragen.",
        "step_3": (
            "Die Anmeldung übernimmt der Client: Er öffnet Keycloak und hält die "
            "Sitzung. Kein Token zum Einfügen."
        ),
        "step_4": (
            "Das Konto entscheidet, welche Modelle erscheinen. Läufe sind asynchrone "
            "Jobs: Ein Start liefert eine Job-ID, die der Client abfragt."
        ),
        "source": "Quellcode",
        "platform": "Plattform",
        "protocol": "Über MCP",
        "health": "Status",
    },
}

# Plain string, not an f-string: the braces are CSS.
_CSS = """
@font-face{font-family:Poppins;font-style:normal;font-weight:400;font-display:swap;
  src:url(/static/poppins-400-latin.woff2) format("woff2")}
@font-face{font-family:Poppins;font-style:normal;font-weight:600;font-display:swap;
  src:url(/static/poppins-600-latin.woff2) format("woff2")}
@font-face{font-family:"Satoshi Variable";font-style:normal;font-weight:300 900;
  font-display:swap;src:url(/static/Satoshi-Variable.woff2) format("woff2")}

:root{
  /* Brand hues, from the logo pinwheel (tokens/colors.css) */
  --dark-blue:#141c32;
  --mid-blue:#0b2f46;
  --navy:#242b42;
  --yellow:oklch(0.777 0.152 83.06);   /* the one true accent */
  --accent-light:oklch(0.777 0.152 83.06 / 60%);
  --ring:oklch(0.704 0.04 256.788);

  --background:#fff;
  --foreground:#000;
  --heading:var(--mid-blue);
  --muted-foreground:oklch(0.554 0.046 257.417);
  --card:#fff;
  --button-foreground:var(--mid-blue);
  --button-border-hover:var(--mid-blue);
  /* Thin, quiet, tinted — not a solid grey rule (design system: borders) */
  --line:color-mix(in oklab, var(--mid-blue) 14%, transparent);
  --shadow-xs:0 1px 2px rgb(0 0 0 / 5%);

  /* Fluid Utopia scales, 360px -> 1600px (tokens/typography.css, spacing.css) */
  --text-step-000:clamp(0.7813rem, 0.7758rem + 0.0242vw, 0.8rem);
  --text-step-00:clamp(0.9375rem, 0.9194rem + 0.0806vw, 1rem);
  --text-step-0:clamp(1.125rem, 1.0887rem + 0.1613vw, 1.25rem);
  --text-step-4:clamp(2.3328rem, 2.1241rem + 0.9277vw, 3.0518rem);
  --spacing-2xs:clamp(0.5625rem, 0.5444rem + 0.0806vw, 0.625rem);
  --spacing-xs:clamp(0.875rem, 0.8569rem + 0.0806vw, 0.9375rem);
  --spacing-s:clamp(1.125rem, 1.0887rem + 0.1613vw, 1.25rem);
  --spacing-m:clamp(1.6875rem, 1.6331rem + 0.2419vw, 1.875rem);
  --spacing-l:clamp(2.25rem, 2.1774rem + 0.3226vw, 2.5rem);
  --spacing-xl:clamp(3.375rem, 3.2661rem + 0.4839vw, 3.75rem);
  --spacing-s-l:clamp(1.125rem, 0.7258rem + 1.7742vw, 2.5rem);

  --heading-letter-spacing:-0.02ch;
  color-scheme:light dark;
}
/* The system has no dark theme, but it does have a dark surface: the footer
   and dark hero sections run on --dark-blue with white text. That is what a
   dark-mode visitor gets, so the palette stays inside the brand. */
@media (prefers-color-scheme:dark){
  :root{
    --background:var(--dark-blue);
    --foreground:#fff;
    --heading:#fff;
    --card:var(--navy);
    --muted-foreground:color-mix(in oklab, #fff 70%, var(--dark-blue));
    --line:color-mix(in oklab, #fff 18%, transparent);
    --button-foreground:#fff;
    --button-border-hover:#fff;
  }
  mark{color:var(--dark-blue)}
}

*{box-sizing:border-box}
body{margin:0;background:var(--background);color:var(--foreground);
  font-family:"Satoshi Variable",ui-sans-serif,system-ui,-apple-system,sans-serif;
  font-size:var(--text-step-0);line-height:1.7;-webkit-font-smoothing:antialiased}
main{max-width:46rem;margin-inline:auto;padding-inline:var(--spacing-s-l);
  padding-block:var(--spacing-xl) var(--spacing-l)}
a{color:inherit;text-decoration-color:var(--accent-light);text-underline-offset:4px;
  text-decoration-thickness:2px}
a:hover{text-decoration-color:var(--yellow)}
:focus-visible{outline:3px solid var(--ring);outline-offset:2px}

/* Poppins carries every label, button and heading; Satoshi only body copy. */
h1,.label,.langs,button,footer{font-family:Poppins,ui-sans-serif,system-ui,sans-serif}

header{display:flex;flex-wrap:wrap;gap:var(--spacing-2xs) var(--spacing-s);
  align-items:center;justify-content:space-between;margin-bottom:var(--spacing-l)}
.org{display:flex;align-items:center;gap:0.625rem;font-family:Poppins,sans-serif;
  font-size:var(--text-step-000);font-weight:600;letter-spacing:0.12em;
  text-transform:uppercase;color:var(--muted-foreground);margin:0}
.org img{width:28px;height:28px}
.langs{font-size:var(--text-step-000);font-weight:500;letter-spacing:0.08em;
  color:var(--muted-foreground);margin:0}
.langs a{text-decoration:none}
.langs [aria-current]{color:var(--foreground);font-weight:600;
  text-decoration:underline;text-decoration-color:var(--yellow);
  text-decoration-thickness:2px}
.langs span{opacity:.4;padding:0 .35rem}

h1{margin:0 0 var(--spacing-s);max-width:25ch;font-size:var(--text-step-4);
  font-weight:600;line-height:1.1;letter-spacing:var(--heading-letter-spacing);
  color:var(--heading);
  /* The brand's block-heading treatment: a 4px accent underline. */
  text-decoration:underline;text-decoration-color:var(--yellow);
  text-decoration-thickness:4px;text-underline-offset:6px}
.lede{margin:0 0 var(--spacing-l);max-width:65ch}

/* Signature highlighter mark, verbatim from the system's base.css. */
mark{--mark-color:var(--accent-light);--mark-skew:0.2em;--mark-height:1.5em;
  background-color:transparent;
  background-image:
    linear-gradient(to bottom right, transparent 50%, var(--mark-color) 50%),
    linear-gradient(var(--mark-color), var(--mark-color)),
    linear-gradient(to top left, transparent 50%, var(--mark-color) 50%);
  background-size:var(--mark-skew) var(--mark-height),
    calc(100% - var(--mark-skew) * 2 + 1px) var(--mark-height),
    var(--mark-skew) var(--mark-height);
  background-position:left center, center, right center;
  background-repeat:no-repeat;color:inherit;
  -webkit-box-decoration-break:clone;box-decoration-break:clone}

.label{margin:0 0 var(--spacing-2xs);font-size:var(--text-step-000);font-weight:600;
  letter-spacing:0.1em;text-transform:uppercase;color:var(--muted-foreground)}

/* Square corners, thin tinted border, 1px shadow — no rounded card, no
   left-accent bar, both explicitly against the system. */
.endpoint{display:flex;flex-wrap:wrap;gap:var(--spacing-xs);align-items:center;
  justify-content:space-between;background:var(--card);border:1px solid var(--line);
  box-shadow:var(--shadow-xs);padding:var(--spacing-xs) var(--spacing-s);
  margin-bottom:var(--spacing-l)}
.endpoint code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-size:var(--text-step-00);overflow-wrap:anywhere;
  /* Without min-width:0 a flex item refuses to shrink below its content, and
     a long endpoint would push the page wider than a phone screen. */
  min-width:0}
/* The outline button: 2px accent border, uppercase Poppins, square, fills with
   accent-light on hover (components/core/Button.jsx). */
.endpoint button{flex:none;height:32px;padding:0 12px;font:inherit;
  font-size:var(--text-step-000);font-weight:500;letter-spacing:0.06em;
  text-transform:uppercase;color:var(--button-foreground);background:var(--card);
  border:2px solid var(--yellow);border-radius:0;box-shadow:var(--shadow-xs);
  appearance:none;-webkit-appearance:none;cursor:pointer;
  transition:background-color .15s ease,border-color .15s ease}
.endpoint button:hover{background:var(--accent-light);color:var(--dark-blue);
  border-color:var(--button-border-hover)}

ol{counter-reset:step;list-style:none;margin:0;padding:0}
ol li{counter-increment:step;display:flex;gap:var(--spacing-xs);
  max-width:65ch;margin-bottom:var(--spacing-xs);color:var(--muted-foreground);
  font-size:var(--text-step-00);line-height:1.6}
/* The numerals are content, not chrome, so they take the heading colour —
   the accent yellow is reserved for borders, underlines and the focus ring,
   and would not carry enough contrast as text. */
ol li::before{content:counter(step);flex:none;width:1.25rem;
  font-family:Poppins,sans-serif;font-weight:600;color:var(--heading);
  font-variant-numeric:tabular-nums}

footer{margin-top:var(--spacing-xl);padding-top:var(--spacing-s);
  border-top:1px solid var(--line);display:flex;flex-wrap:wrap;
  gap:var(--spacing-2xs) var(--spacing-m);align-items:baseline;
  font-size:var(--text-step-000);color:var(--muted-foreground)}
footer a{text-decoration:none}
footer a:hover{text-decoration:underline;text-decoration-color:var(--yellow);
  text-decoration-thickness:2px}
footer .version{margin-left:auto;font-variant-numeric:tabular-nums}
"""

_SCRIPT = """
const b=document.querySelector('[data-copy]');
if(b&&navigator.clipboard){b.hidden=false;b.addEventListener('click',async()=>{
  try{await navigator.clipboard.writeText(b.dataset.copy);
    const o=b.textContent;b.textContent=b.dataset.done;
    setTimeout(()=>{b.textContent=o},1600);}catch(e){}
});}
"""


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def pick_language(request: Request) -> str:
    """?lang= wins; otherwise the first understood tag in Accept-Language."""
    requested = request.query_params.get("lang", "").lower()
    if requested in LANGUAGES:
        return requested
    for part in request.headers.get("accept-language", "").split(","):
        tag = part.split(";")[0].strip().lower()
        if tag[:2] in LANGUAGES:
            return tag[:2]
    return DEFAULT_LANGUAGE


def endpoint_url(request: Request, settings: Settings) -> str:
    """The URL a client should be pointed at.

    `resource_url` is the configured truth when OAuth discovery is on. Without
    it the request is the only source, and behind the ingress that means
    trusting X-Forwarded-Proto — the app itself only ever sees plain http.
    """
    if settings.resource_url:
        return settings.resource_url
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    scheme = forwarded or request.url.scheme
    return f"{scheme}://{request.url.netloc}/mcp"


def render(lang: str, endpoint: str) -> str:
    t = TEXT[lang]
    other = "de" if lang == "en" else "en"
    url = _escape(endpoint)
    description = t["lede_before"] + t["lede_mark"] + t["lede_after"]
    return f"""<!doctype html>
<html lang="{lang}">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{_escape(t["title"])}</title>
<meta name="description" content="{_escape(description)}">
<link rel="icon" href="/static/ufc-mark.png" type="image/png">
<link rel="alternate" hreflang="{other}" href="?lang={other}">
<style>{_CSS}</style>
<main>
  <header>
    <p class="org"><img src="/static/ufc-mark.png" alt="" width="28" height="28"
      >{_escape(t["org"])}</p>
    <p class="langs">
      <a href="?lang=en"{' aria-current="true"' if lang == "en" else ""}>EN</a><span>/</span
      ><a href="?lang=de"{' aria-current="true"' if lang == "de" else ""}>DE</a>
    </p>
  </header>

  <h1>{_escape(t["title"])}</h1>
  <p class="lede">{_escape(t["lede_before"])}<mark>{_escape(t["lede_mark"])}</mark
    >{_escape(t["lede_after"])}</p>

  <p class="label">{_escape(t["endpoint_label"])}</p>
  <div class="endpoint">
    <code>{url}</code>
    <button type="button" hidden data-copy="{url}" data-done="{_escape(t["copied"])}"
      >{_escape(t["copy"])}</button>
  </div>

  <p class="label">{_escape(t["steps_label"])}</p>
  <ol>
    <li><span>{_escape(t["step_1_before"])}<a href="{PLATFORM_URL}"
      >{_escape(t["step_1_link"])}</a>{_escape(t["step_1_after"])}</span></li>
    <li><span>{_escape(t["step_2"])}</span></li>
    <li><span>{_escape(t["step_3"])}</span></li>
    <li><span>{_escape(t["step_4"])}</span></li>
  </ol>

  <footer>
    <a href="{PLATFORM_URL}">{_escape(t["platform"])}</a>
    <a href="{REPOSITORY_URL}">{_escape(t["source"])}</a>
    <a href="{PROTOCOL_URL}">{_escape(t["protocol"])}</a>
    <a href="/health">{_escape(t["health"])}</a>
    <span class="version">v{_escape(__version__)}</span>
  </footer>
</main>
<script>{_SCRIPT}</script>
"""


def landing_routes(settings: Settings) -> list[Route]:
    async def landing(request: Request) -> Response:
        lang = pick_language(request)
        html = render(lang, endpoint_url(request, settings))
        return HTMLResponse(html, headers={"Vary": "Accept-Language"})

    async def static(request: Request) -> Response:
        name = request.path_params["name"]
        media_type = _STATIC_FILES.get(name)
        if media_type is None:
            return Response(status_code=404)
        return FileResponse(
            f"{_STATIC_DIR}/{name}",
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    return [
        Route("/", landing, methods=["GET", "HEAD"]),
        Route("/static/{name}", static, methods=["GET", "HEAD"]),
    ]

"""Rendering helpers for the minimal admin UI."""

from __future__ import annotations

from html import escape
from urllib.parse import urlencode

from moe_toolkit.admin.beta_keys import BetaKeyRecord, render_install_command


def mask_api_key(api_key: str) -> str:
    """Masks an API key for dashboard display."""

    if len(api_key) <= 12:
        return api_key
    return f"{api_key[:10]}...{api_key[-6:]}"


def build_admin_login_page(*, message: str = "", error: str = "") -> str:
    """Builds the admin login HTML page."""

    status_html = ""
    if message:
        status_html = f'<p class="notice notice-success">{escape(message)}</p>'
    if error:
        status_html += f'<p class="notice notice-error">{escape(error)}</p>'

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>MOE Toolkit Admin Login</title>
    <style>
      :root {{
        color-scheme: light;
        --bg: #f3f6fb;
        --panel: #ffffff;
        --ink: #0f172a;
        --muted: #475569;
        --line: #dbe3f0;
        --accent: #0f766e;
        --accent-soft: #d1fae5;
        --danger: #b91c1c;
        --danger-soft: #fee2e2;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        padding: 24px;
        background:
          radial-gradient(circle at top left, rgba(15, 118, 110, 0.12), transparent 32%),
          linear-gradient(180deg, #edf4ff 0%, var(--bg) 100%);
        color: var(--ink);
        font-family: "SF Pro Display", "Helvetica Neue", sans-serif;
      }}
      main {{
        width: min(440px, 100%);
        padding: 32px;
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 24px;
        box-shadow: 0 24px 64px rgba(15, 23, 42, 0.12);
      }}
      h1 {{ margin: 0 0 10px; font-size: 2rem; }}
      p {{ color: var(--muted); line-height: 1.6; }}
      label {{
        display: block;
        margin: 18px 0 8px;
        font-size: 0.92rem;
        font-weight: 600;
        color: var(--ink);
      }}
      input {{
        width: 100%;
        padding: 12px 14px;
        border: 1px solid var(--line);
        border-radius: 14px;
        font-size: 1rem;
      }}
      button {{
        width: 100%;
        margin-top: 22px;
        padding: 13px 16px;
        border: 0;
        border-radius: 999px;
        background: var(--accent);
        color: white;
        font-size: 1rem;
        font-weight: 700;
        cursor: pointer;
      }}
      .notice {{
        margin: 16px 0 0;
        padding: 12px 14px;
        border-radius: 14px;
        font-size: 0.95rem;
      }}
      .notice-success {{
        background: var(--accent-soft);
        color: #065f46;
      }}
      .notice-error {{
        background: var(--danger-soft);
        color: var(--danger);
      }}
    </style>
  </head>
  <body>
    <main>
      <h1>MOE Admin</h1>
      <p>Use the admin account to manage beta users, issue API keys, revoke access, and download install email templates.</p>
      {status_html}
      <form method="post" action="/admin/login">
        <label for="username">Username</label>
        <input id="username" name="username" type="text" autocomplete="username" required />
        <label for="password">Password</label>
        <input id="password" name="password" type="password" autocomplete="current-password" required />
        <button type="submit">Sign In</button>
      </form>
    </main>
  </body>
</html>"""


def build_admin_dashboard(
    *,
    records: list[BetaKeyRecord],
    csrf_token: str,
    server_url: str,
    message: str = "",
    error: str = "",
) -> str:
    """Builds the admin dashboard HTML page."""

    status_html = ""
    if message:
        status_html = f'<p class="notice notice-success">{escape(message)}</p>'
    if error:
        status_html += f'<p class="notice notice-error">{escape(error)}</p>'

    record_rows = []
    for record in sorted(records, key=lambda item: item.created_at, reverse=True):
        template_query = urlencode({"download": "1"})
        manifest_query = urlencode({"status": "active"})
        install_command = render_install_command(
            api_key=record.api_key,
            server_url=server_url,
            host=record.host_client,
        )
        revoke_form = ""
        if record.status == "active":
            revoke_form = f"""
              <form method="post" action="/admin/revoke" class="inline-form">
                <input type="hidden" name="csrf_token" value="{escape(csrf_token)}" />
                <input type="hidden" name="key_id" value="{escape(record.key_id)}" />
                <button type="submit" class="danger-button">Revoke</button>
              </form>
            """
        record_rows.append(
            f"""
            <tr>
              <td>{escape(record.owner_name)}</td>
              <td>{escape(record.contact or "-")}</td>
              <td><code>{escape(record.key_id)}</code></td>
              <td><code>{escape(mask_api_key(record.api_key))}</code></td>
              <td>{escape(record.host_client)}</td>
              <td>{escape(record.status)}</td>
              <td class="actions">
                <a href="/admin/email-template/{escape(record.key_id)}.txt?{template_query}">Email</a>
                <a href="/admin/install-command/{escape(record.key_id)}">Install</a>
                {revoke_form}
              </td>
            </tr>
            <tr class="subrow">
              <td colspan="7"><small>{escape(install_command)}</small></td>
            </tr>
            """
        )

    active_count = sum(1 for record in records if record.status == "active")
    revoked_count = sum(1 for record in records if record.status == "revoked")
    rows_html = "\n".join(record_rows) or '<tr><td colspan="7" class="empty">No beta users yet.</td></tr>'

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>MOE Toolkit Admin</title>
    <style>
      :root {{
        color-scheme: light;
        --bg: #f6f8fc;
        --panel: #ffffff;
        --ink: #0f172a;
        --muted: #475569;
        --line: #dbe3f0;
        --accent: #0f766e;
        --accent-soft: #d1fae5;
        --danger: #b91c1c;
        --danger-soft: #fee2e2;
        --shadow: rgba(15, 23, 42, 0.08);
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        padding: 32px;
        background:
          radial-gradient(circle at top right, rgba(14, 165, 233, 0.1), transparent 26%),
          radial-gradient(circle at top left, rgba(15, 118, 110, 0.1), transparent 22%),
          var(--bg);
        color: var(--ink);
        font-family: "SF Pro Display", "Helvetica Neue", sans-serif;
      }}
      header {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        margin-bottom: 20px;
      }}
      h1 {{ margin: 0; font-size: 2.1rem; }}
      .top-actions {{
        display: flex;
        gap: 12px;
        flex-wrap: wrap;
      }}
      .shell, .panel {{
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 22px;
        box-shadow: 0 24px 64px var(--shadow);
      }}
      .shell {{ padding: 26px; }}
      .grid {{
        display: grid;
        grid-template-columns: minmax(320px, 420px) 1fr;
        gap: 24px;
        align-items: start;
      }}
      .panel {{ padding: 22px; }}
      h2 {{ margin-top: 0; font-size: 1.15rem; }}
      .statline {{
        display: flex;
        gap: 12px;
        flex-wrap: wrap;
        color: var(--muted);
        margin: 0 0 18px;
      }}
      label {{
        display: block;
        margin: 14px 0 8px;
        font-size: 0.92rem;
        font-weight: 600;
      }}
      input, select, textarea {{
        width: 100%;
        padding: 11px 13px;
        border: 1px solid var(--line);
        border-radius: 14px;
        font-size: 0.98rem;
      }}
      textarea {{ min-height: 88px; resize: vertical; }}
      button, .link-button {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 11px 16px;
        border: 0;
        border-radius: 999px;
        font-size: 0.96rem;
        font-weight: 700;
        text-decoration: none;
        cursor: pointer;
      }}
      .primary-button, .link-button {{
        background: var(--accent);
        color: #fff;
      }}
      .danger-button {{
        background: var(--danger-soft);
        color: var(--danger);
      }}
      .notice {{
        margin: 0 0 18px;
        padding: 12px 14px;
        border-radius: 14px;
      }}
      .notice-success {{
        background: var(--accent-soft);
        color: #065f46;
      }}
      .notice-error {{
        background: var(--danger-soft);
        color: var(--danger);
      }}
      table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 0.95rem;
      }}
      th, td {{
        text-align: left;
        padding: 12px 10px;
        border-bottom: 1px solid #edf2f7;
        vertical-align: top;
      }}
      th {{
        color: var(--muted);
        font-size: 0.82rem;
        text-transform: uppercase;
        letter-spacing: 0.04em;
      }}
      .subrow td {{
        padding-top: 0;
        color: var(--muted);
      }}
      .actions {{
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
      }}
      .actions a {{
        color: var(--accent);
        font-weight: 600;
        text-decoration: none;
      }}
      .inline-form {{
        margin: 0;
      }}
      code, small {{
        font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      }}
      .muted {{
        color: var(--muted);
      }}
      .empty {{
        color: var(--muted);
        text-align: center;
      }}
      @media (max-width: 980px) {{
        body {{ padding: 18px; }}
        .grid {{ grid-template-columns: 1fr; }}
      }}
    </style>
  </head>
  <body>
    <div class="shell">
      <header>
        <div>
          <h1>MOE Admin</h1>
          <p class="muted">Manage beta users, issue API keys, and export install templates.</p>
        </div>
        <div class="top-actions">
          <a class="link-button" href="/admin/email-manifest.csv?status=active">Download Active CSV</a>
          <form method="post" action="/admin/logout">
            <input type="hidden" name="csrf_token" value="{escape(csrf_token)}" />
            <button type="submit" class="danger-button">Sign Out</button>
          </form>
        </div>
      </header>
      {status_html}
      <div class="grid">
        <section class="panel">
          <h2>Issue Beta Key</h2>
          <p class="statline">
            <span>Active: <strong>{active_count}</strong></span>
            <span>Revoked: <strong>{revoked_count}</strong></span>
            <span>Cloud: <code>{escape(server_url)}</code></span>
          </p>
          <form method="post" action="/admin/issue">
            <input type="hidden" name="csrf_token" value="{escape(csrf_token)}" />
            <label for="owner_name">Owner Name</label>
            <input id="owner_name" name="owner_name" type="text" required />
            <label for="contact">Contact</label>
            <input id="contact" name="contact" type="text" />
            <label for="host_client">Host Client</label>
            <select id="host_client" name="host_client">
              <option value="codex-cli">codex-cli</option>
              <option value="claude-code">claude-code</option>
            </select>
            <label for="note">Note</label>
            <textarea id="note" name="note"></textarea>
            <button type="submit" class="primary-button">Issue Key</button>
          </form>
        </section>
        <section class="panel">
          <h2>Beta Users</h2>
          <table>
            <thead>
              <tr>
                <th>User</th>
                <th>Contact</th>
                <th>Key ID</th>
                <th>API Key</th>
                <th>Host</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows_html}
            </tbody>
          </table>
        </section>
      </div>
    </div>
  </body>
</html>"""

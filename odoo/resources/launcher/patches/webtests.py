import logging
import os
import re
import subprocess
import time

import odoo.tests.common
from odoo import api
from odoo.release import version_info
from odoo.service import security
from odoo.tests.common import (
    get_db_name,
    HOST,
    Opener,
)

major_version = version_info[0]
if isinstance(major_version, str):
    major_version = int(major_version.lstrip("saas~"))

version = float(f"{major_version}.{version_info[1]}")

if version >= 16.4:
    from .ChromeBrowser import ChromeBrowser as ChromeBrowser16
    from .browser_js import browser_js_ge_16_4


class LogReplacement:
    def __init__(
        self, regex: str, format: str, markup: bool = True, highlighter: bool = None
    ):
        self.regex = re.compile(regex)
        self.format = format
        self.markup = markup
        self.highlighter = highlighter


class CustomAdapter(logging.LoggerAdapter):
    replacements = [
        LogReplacement(
            r"^\"(?P<name>.*)\" passed (?P<count>\d+) tests\.$",
            "[bold steel_blue1 underline]{name}[/] passed [green]{count}[/] tests",
        ),
        LogReplacement(
            r"^Tour (?P<tour>.*): step '(?:Click here to go to the next step\. )?\(trigger: (?P<step>.*)\)' succeeded",
            "Step [underline][bold steel_blue1]{step}[/bold steel_blue1][/underline] succeeded",
        ),
        LogReplacement(
            r"^Running tour (?P<tour>.*)",
            "Running tour [underline rgb(249,38,114)]{tour}[/]",
        ),
        LogReplacement(
            r"Tour (?P<tour>.*) failed at step (?P<step>.*)",
            "Tour {tour} failed at step [bold reverse red]{step}[/]",
        ),
        LogReplacement(r"^Owl is running in 'dev' mode", None),
        LogReplacement(r"^Views: using legacy view:", None),
        LogReplacement(r"^<html><head>", None),
        LogReplacement(
            r"^\[rpc\] response(?P<args>.*)",
            "[rpc] response {args}",
            markup=False,
            highlighter=True,
        ),
    ]

    def runbot(self, message, *args, **kws):
        self.log(25, message, *args, **kws)

    def log(self, *args, **kwargs):
        if len(args) < 3:
            return self.logger.log(*args, **kwargs)
        level, fmt, msg = args[:3]
        msg = str(msg)

        # TODO: match fmt in replacements
        if fmt == "Screenshot in: %s" and os.environ.get("TERM") == "xterm-kitty":
            subprocess.run(["kitty", "+kitten", "icat", msg])
            return

        for replacement in self.replacements:
            if match := replacement.regex.match(msg):
                if replacement.format is None:
                    return
                groups = match.groupdict()
                msg = replacement.format.format(**groups)
                extra = kwargs.get("extra", {})
                extra["markup"] = replacement.markup
                if not replacement.highlighter:
                    extra["highlighter"] = None
                kwargs["extra"] = extra
                break

        args = [level, fmt, msg] + list(args[3:])
        return self.logger.log(*args, **kwargs)

    def getChild(self, *args, **kwargs):
        return CustomAdapter(self.logger.getChild(*args, **kwargs), {})


def init_chrome(super):
    def decorator(self, *args, **kwargs):
        super(self, *args, **kwargs)
        self._logger = CustomAdapter(self._logger, {})

    return decorator


def _spawn_chrome_lt_16_4(super):
    def decorator(self, cmd):
        if "--remote-allow-origins=*" not in cmd:
            cmd.insert(len(cmd) - 1, "--remote-allow-origins=*")
        return super(self, cmd)

    return decorator


def _find_websocket_lt_16(self):
    version = self._json_command("version")
    self._logger.info("Browser version: %s", version["Browser"])
    infos = self._json_command("", get_key=0)  # Infos about the first tab
    self.ws_url = infos["webSocketDebuggerUrl"]
    self.dev_tools_frontend_url = infos.get("devtoolsFrontendUrl")
    self._logger.info(
        "Chrome headless temporary user profile dir: %s", self.user_data_dir
    )


ChromeBrowser = odoo.tests.common.ChromeBrowser

if version >= 16.4:
    ChromeBrowser = ChromeBrowser16


@classmethod
def start_browser_ge_16_4(cls):
    if cls.browser is None:
        cls.browser = ChromeBrowser(cls)
        cls.addClassCleanup(cls.terminate_browser)


@classmethod
def terminate_browser_ge_16_4(cls):
    if cls.browser:
        cls.browser.stop()
        cls.browser = None


def authenticate_ge_16_4(self, user, password):
    if getattr(self, "session", None):
        odoo.http.root.session_store.delete(self.session)

    self.session = session = odoo.http.root.session_store.new()
    session.update(odoo.http.get_default_session(), db=get_db_name())
    session.context["lang"] = odoo.http.DEFAULT_LANG

    if user:
        self.cr.flush()
        self.cr.clear()
        uid = self.registry["res.users"].authenticate(
            session.db, user, password, {"interactive": False}
        )
        env = api.Environment(self.cr, uid, {})
        session.uid = uid
        session.login = user
        session.session_token = uid and security.compute_session_token(session, env)
        session.context = dict(env["res.users"].context_get())

    odoo.http.root.session_store.save(session)
    self.opener = Opener(self.cr)
    self.opener.cookies["session_id"] = session.sid
    if self.browser:
        self._logger.info("Setting session cookie in browser")
        self.browser.set_cookie("session_id", session.sid, "/", HOST)

    return session


def browser_js_lt_16_4(super):
    def decorator(self, *args, **kwargs):
        if os.environ.get("QUNIT_WATCH") == "1":
            kwargs["watch"] = True
        super(self, *args, **kwargs)

    return decorator


@classmethod
def start_browser_lt_16(cls):
    if cls.browser is None:
        cls.browser = ChromeBrowser(cls._logger, cls.browser_size, cls.__name__)
        cls.addClassCleanup(cls.terminate_browser)
    if os.environ.get("QUNIT_WATCH") == "1":
        debug_front_end = f"http://127.0.0.1:{cls.browser.devtools_port}{cls.browser.dev_tools_frontend_url}"
        cls.browser._spawn_chrome([cls.browser.executable, debug_front_end])
        time.sleep(3)


def _wait_code_ok_lt_16(super):
    def decorator(self, code, timeout):
        if os.environ.get("QUNIT_WATCH") == "1":
            timeout = max(timeout * 10, 3600)
        return super(self, code, timeout)

    return decorator


def start_tour(super):
    def decorator(*args, **kwargs):
        if os.environ.get("STEP_DELAY"):
            kwargs["step_delay"] = int(os.environ.get("STEP_DELAY"))
        super(*args, **kwargs)

    return decorator


class WebTests:
    def apply(self):
        # Override the logger to highlight the output with rich
        ChromeBrowser.__init__ = init_chrome(ChromeBrowser.__init__)

        # Add --remote-allow-origins to chrome
        if version < 16.4:
            ChromeBrowser._spawn_chrome = _spawn_chrome_lt_16_4(
                ChromeBrowser._spawn_chrome
            )

        # Backport the watch option before 16
        if version < 16:
            ChromeBrowser._find_websocket = _find_websocket_lt_16
            ChromeBrowser._wait_code_ok = _wait_code_ok_lt_16(
                ChromeBrowser._wait_code_ok
            )
            odoo.tests.HttpCase.start_browser = start_browser_lt_16

        # Override watch if QUNIT_WATCH is set
        if version < 16.4:
            odoo.tests.HttpCase.browser_js = browser_js_lt_16_4(
                odoo.tests.HttpCase.browser_js
            )

        # Revert this 2b0d9fa6a9f6a5c7ba839922a3ca2114cdfe5eb8
        # This launches a new chrome instance for every tour...
        # Basically copy the code from 16.0
        if version >= 16.4:
            odoo.tests.common.ChromeBrowser = ChromeBrowser16
            odoo.tests.HttpCase.browser_js = browser_js_ge_16_4
            odoo.tests.HttpCase.start_browser = start_browser_ge_16_4
            odoo.tests.HttpCase.terminate_browser = terminate_browser_ge_16_4
            odoo.tests.HttpCase.authenticate = authenticate_ge_16_4

        # Override step_delay if STEP_DELAY is set
        odoo.tests.HttpCase.start_tour = start_tour(odoo.tests.HttpCase.start_tour)

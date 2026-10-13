#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["typer", "rich"]
# ///
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import URLError
from urllib.parse import urlsplit, parse_qs

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("e3p", ROOT / "scripts/e3p.py")
e3p = importlib.util.module_from_spec(spec)
sys.modules["e3p"] = e3p
spec.loader.exec_module(e3p)
CREDS = {"base": "https://example.test", "token": "synthetic-token&value", "userid": 123}


class DownloadTest(unittest.TestCase):
    def failure(self, url, opener=None):
        captured = io.StringIO()
        with patch.object(e3p, "_load_creds", return_value=CREDS), patch.object(e3p, "build_opener", return_value=opener) as builder:
            with contextlib.redirect_stdout(captured), self.assertRaises(SystemExit):
                e3p.download(url, out=Path("unused"))
        return captured.getvalue(), builder

    def test_foreign_or_non_file_urls_never_receive_credentials(self):
        for url in ["https://foreign.test/pluginfile.php/file", "http://example.test/pluginfile.php/file", "https://example.test/not-a-file", "https://user@example.test/pluginfile.php/file"]:
            with self.subTest(url=url):
                output, builder = self.failure(url)
                builder.assert_not_called()
                self.assertNotIn(CREDS["token"], output)
                self.assertEqual(json.loads(output)["error"]["message"], "invalid download URL")

    def test_failed_download_never_reports_token_or_request_url(self):
        opener = MagicMock()
        opener.open.side_effect = URLError("failed https://example.test/pluginfile.php/file?token=" + CREDS["token"])
        output, _ = self.failure("https://example.test/pluginfile.php/file", opener)
        self.assertNotIn(CREDS["token"], output)
        self.assertNotIn("token=", output)
        self.assertEqual(json.loads(output)["error"]["message"], "download failed")

    def test_success_encodes_token_once_and_writes_requested_file(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = b"example file"
        with tempfile.TemporaryDirectory() as tmp, patch.object(e3p, "_load_creds", return_value=CREDS), patch.object(e3p, "build_opener", return_value=opener):
            out = Path(tmp) / "file.pdf"
            with contextlib.redirect_stdout(io.StringIO()):
                e3p.download("https://example.test/webservice/pluginfile.php/file.pdf?token=old&forcedownload=1", out=out)
            request = opener.open.call_args.args[0]
            query = parse_qs(urlsplit(request.full_url).query)
            self.assertEqual(query["token"], [CREDS["token"]])
            self.assertEqual(query["forcedownload"], ["1"])
            self.assertEqual(out.read_bytes(), b"example file")

    def test_cross_origin_redirect_is_rejected(self):
        with self.assertRaises(ValueError):
            e3p._DownloadRedirect(CREDS["base"]).redirect_request(None, None, 302, "", {}, "https://foreign.test/pluginfile.php/file")


class AnnouncementsTest(unittest.TestCase):
    def test_html_to_text_keeps_paragraphs(self):
        self.assertEqual(e3p._html_to_text("<p>Hi&nbsp; all</p><p>Line<br>two</p>"), "Hi all\nLine\ntwo")

    def test_lists_recent_news_posts_only(self):
        now = int(e3p.datetime.now().timestamp())
        def ws(function, **params):
            if function == "mod_forum_get_forums_by_courses":
                return [{"id": 1, "course": 9, "type": "news"}, {"id": 2, "course": 9, "type": "general"}]
            self.assertEqual(params["forumid"], 1)
            return {"discussions": [
                {"discussion": 5, "subject": "old", "created": now - 40 * 86400, "pinned": True, "message": ""},
                {"discussion": 6, "subject": "new", "created": now - 86400, "message": "<p>hello</p>", "attachments": [{"filename": "a.pdf", "fileurl": "https://example.test/webservice/pluginfile.php/a.pdf"}]},
            ]}
        captured = io.StringIO()
        with patch.object(e3p, "_load_creds", return_value=CREDS), patch.object(e3p, "_ws", side_effect=ws), contextlib.redirect_stdout(captured):
            e3p.announcements(courseid=9, days=30, limit=20)
        out = captured.getvalue()
        self.assertNotIn(CREDS["token"], out)
        rows = json.loads(out)["data"]
        self.assertEqual([r["subject"] for r in rows], ["new"])
        self.assertEqual(rows[0]["message"], "hello")
        self.assertEqual(rows[0]["url"], "https://example.test/mod/forum/discuss.php?d=6")
        self.assertEqual(rows[0]["attachments"][0]["name"], "a.pdf")


if __name__ == "__main__": unittest.main()

import unittest
from unittest.mock import patch

import app_launcher
import tools


class AppLauncherTests(unittest.TestCase):
    def test_chrome_request_uses_browser_discovery_and_fallback(self):
        with patch.object(app_launcher, "_open_in_chrome", return_value="default") as open_browser:
            result = app_launcher.launch_app("open Chrome")

        self.assertIn("default browser", result)
        open_browser.assert_called_once_with()

    def test_spotify_and_youtube_open_web_urls(self):
        cases = (
            ("Open Spotify", "https://open.spotify.com/", "Spotify"),
            ("Open Spotify in Chrome", "https://open.spotify.com/", "Spotify"),
            ("open YouTube", "https://www.youtube.com/", "YouTube"),
        )
        for request, url, service in cases:
            with self.subTest(request=request):
                with patch.object(app_launcher, "_open_in_chrome", return_value="chrome") as open_browser:
                    result = app_launcher.launch_app(request)

                self.assertEqual(result, f"Opening {service} in Chrome.")
                open_browser.assert_called_once_with(url)

    def test_browser_services_fall_back_to_default_browser(self):
        with patch.object(app_launcher, "_find_chrome_executable", return_value=""), \
             patch.object(app_launcher.webbrowser, "open", return_value=True) as open_browser:
            result = app_launcher._open_in_chrome("https://www.youtube.com/")

        self.assertEqual(result, "default")
        open_browser.assert_called_once_with("https://www.youtube.com/", new=2)

    def test_system_control_routes_browser_services_through_app_launcher(self):
        with patch.object(app_launcher, "launch_app", return_value="Opening YouTube in Chrome.") as launch:
            result = tools.system_control("open", "YouTube")

        self.assertEqual(result, "Opening YouTube in Chrome.")
        launch.assert_called_once_with("YouTube")


if __name__ == "__main__":
    unittest.main()

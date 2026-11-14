"""The Android TV and Google TV build of Sofa's TV app (android/, the `googletv` flavor).

One app, two builds: the Fire TV app as it has always been (the same name on the device and the same key, so a new
build installs over the old one), and a build for Android TV and Google TV under a name of its own, which the
repository's public sideload key never signs. GitHub builds both and works the second on an Android TV emulator
(android/tv_check.py); here, what must stay true of the files.
"""
import os
import re
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


class TheTwoBuilds(unittest.TestCase):
    def setUp(self):
        self.gradle = read("android", "app", "build.gradle.kts")

    def flavor(self, name):
        m = re.search(r'create\("%s"\) \{(.*?)\n        \}' % name, self.gradle, re.S)
        self.assertTrue(m, name)
        return m.group(1)

    def test_the_fire_tv_app_is_what_it_was(self):
        self.assertIn('applicationId = "uk.edgeventure.sofa"', self.gradle)           # the default: the Fire TV app's
        fire = self.flavor("firetv")
        self.assertNotIn("applicationId", fire)                                        # so a new build installs over the old
        self.assertIn('signingConfig = signingConfigs.getByName("sideload")', fire)
        self.assertIn("minSdk = 22", self.gradle)                                      # Fire OS 5

    def test_the_tv_build_has_its_own_name_and_never_the_public_key(self):
        tv = self.flavor("googletv")
        self.assertIn('applicationId = "uk.edgeventure.sofa.tv"', tv)
        self.assertIn('signingConfig = signingConfigs.findByName("store")', tv)        # the owner's key, or none
        self.assertNotIn("sideload", tv)
        self.assertIn('System.getenv("SOFA_TV_KEYSTORE")', self.gradle)
        for secret in ("SOFA_TV_KEYSTORE_PASSWORD", "SOFA_TV_KEY_ALIAS", "SOFA_TV_KEY_PASSWORD"):
            self.assertIn('System.getenv("%s")' % secret, self.gradle)                 # from the environment, not from a file here
        release = re.search(r'getByName\("release"\) \{(.*?)\}', self.gradle, re.S).group(1)
        self.assertNotIn("signingConfig", release)                # (a build type's key would sign both builds alike)
        self.assertNotIn('getByName("debug")', self.gradle)

    def test_no_key_but_the_sideload_one_is_in_the_repository(self):
        try:
            out = subprocess.run(["git", "-C", ROOT, "ls-files"], capture_output=True, text=True, timeout=30)
        except OSError:
            self.skipTest("no git here")
        if out.returncode != 0 or not out.stdout.strip():
            self.skipTest("not a clone")
        keys = [f for f in out.stdout.split("\n") if re.search(r"\.(jks|keystore|p12|pfx|pem|key)$", f) and "/tests/" not in "/" + f]
        self.assertEqual([k for k in keys if k.startswith("android/")], ["android/sofa-sideload.jks"])

    def test_it_says_its_for_tvs(self):
        main, tv = read("android", "app", "src", "main", "AndroidManifest.xml"), read("android", "app", "src", "googletv", "AndroidManifest.xml")
        self.assertIn("android.intent.category.LEANBACK_LAUNCHER", main)               # on the TV's home screen
        self.assertIn('android:banner="@drawable/banner"', main)
        self.assertRegex(main, r'android\.hardware\.touchscreen"\s+android:required="false"')
        self.assertRegex(tv, r'(?s)android\.software\.leanback"\s+android:required="true"\s+tools:replace="android:required"')
        self.assertNotRegex(main + tv, r"uses-permission[^>]*(CAMERA|RECORD_AUDIO|ACCESS_FINE_LOCATION|READ_CONTACTS)")

    def test_each_build_says_which_it_is(self):
        activity = read("android", "app", "src", "main", "java", "uk", "edgeventure", "sofa", "MainActivity.kt")
        self.assertIn('SofaApp/1 (${BuildConfig.DEVICE})', activity)                   # Sofa's pages can tell the two apart
        self.assertIn('buildConfigField("String", "DEVICE", "\\"FireTV\\"")', self.gradle)       # the Fire TV app's name: as before
        self.assertIn('buildConfigField("String", "DEVICE", "\\"GoogleTV\\"")', self.gradle)
        self.assertIn("if (BuildConfig.DEBUG) WebView.setWebContentsDebuggingEnabled(true)", activity)   # never a release
        start = read("android", "app", "src", "main", "assets", "start.html")
        self.assertIn("SofaNative.device()", start)
        self.assertNotIn("for Fire TV", start)

    def test_github_builds_both_and_checks_the_keys(self):
        flow = read(".github", "workflows", "android.yml")
        self.assertIn("gradle assembleFiretvRelease assembleGoogletvDebug bundleGoogletvRelease", flow)
        self.assertIn("app-firetv-release.apk sofa-firetv.apk", flow)                  # the name Sofa fetches (sofa/apps.py)
        self.assertIn("app-googletv-release.aab sofa-googletv.aab", flow)              # Google Play takes bundles
        self.assertIn('[ "$firetv" = "$sideload" ]', flow)                             # the Fire TV app keeps its key,
        self.assertIn('[ "$googletv" != "$sideload" ]', flow)                          # the Google TV app never has it
        self.assertIn("secrets.SOFA_TV_KEYSTORE_BASE64", flow)
        published = flow.split("Publish the Fire TV app (main only)", 1)[1].split("\n  tv:", 1)[0]
        self.assertIn("files: sofa-firetv.apk", published)
        self.assertNotIn("googletv", published)                                        # nothing of the TV build is published
        self.assertIn("target: android-tv", flow)
        self.assertIn("python3 android/tv_check.py sofa-googletv-debug.apk", flow)
        self.assertRegex(flow, r"(?m)^permissions:\n  contents: read$")                # only the Fire TV release writes


if __name__ == "__main__":
    unittest.main()

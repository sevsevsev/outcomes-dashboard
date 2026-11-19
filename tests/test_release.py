import release


def test_release_shows_three_pages_and_the_wheel_only():
    assert release.shown_pages(False) == ("map", "peers", "schools")
    assert release.shown_views(False) == ("Wheel",)


def test_flag_brings_everything_back():
    assert release.shown_pages(True) == release.ALL_PAGES
    assert release.shown_views(True) == ("Wheel", "Ranked")


def test_flag_reads_environment_and_secrets():
    assert not release.flag_on({}, {})
    assert release.flag_on({"SHOW_ALL_PAGES": "1"}, {})
    assert release.flag_on({}, {"SHOW_ALL_PAGES": True})
    assert not release.flag_on({"SHOW_ALL_PAGES": "0"}, {"SHOW_ALL_PAGES": "no"})


class Broken(dict):
    def get(self, key, default=None):
        raise FileNotFoundError("no secrets file")


def test_missing_secrets_file_is_off():
    assert not release.flag_on({}, Broken())

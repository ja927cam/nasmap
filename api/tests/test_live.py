from app.services import live


def test_rainviewer_max_zoom():
    assert live.RAINVIEWER_MAX_ZOOM == 7


def test_rainviewer_template():
    url = live.rainviewer_template("https://tilecache.rainviewer.com", "/v2/radar/abc")
    assert url == "https://tilecache.rainviewer.com/v2/radar/abc/256/{z}/{x}/{y}/4/1_1.png"


def test_wmo_descriptions():
    assert live.wmo_description(0) == "Clear"
    assert live.wmo_description(95) == "Thunderstorm"
    assert live.wmo_description(999) == "Unknown"

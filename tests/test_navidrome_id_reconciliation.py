import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.api import navidrome as navidrome_api
from app.database.models import AppSetting, Playlist, PlaylistTrack, Song, SongSourceIdentity
from app.database.session import SessionLocal
from app.services import playlist_manager
from app.services.navidrome import NavidromeClient, navidrome_id_scheme, parse_server_version
from app.services.navidrome_id_reconciliation import (
    STATE_KEY,
    NavidromeIdReconciler,
    normalize_library_path,
)
from app.services.operations import export_settings, import_settings


MUSIC = "/music"


def _settings(**overrides):
    values = {
        "navidrome_url": "http://navidrome:4533",
        "navidrome_username": "harmony",
        "navidrome_password": "secret",
        "navidrome_timeout_seconds": 2,
        "navidrome_max_retries": 0,
        "music_path": MUSIC,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeNavidrome:
    """Minimal Subsonic server exposing only the read endpoints Harmony uses."""

    def __init__(self, *, version="0.64.0", songs=(), playlists=(), scanning=False):
        self.version = version
        self.songs = list(songs)
        self.playlists = list(playlists)
        self.scanning = scanning
        self.calls = []

    def _ok(self, **body):
        return httpx.Response(
            200,
            json={"subsonic-response": {"status": "ok", "serverVersion": self.version, **body}},
        )

    def handler(self, request):
        action = request.url.path.rsplit("/", 1)[-1]
        params = request.url.params
        self.calls.append(action)
        if action == "getScanStatus":
            return self._ok(scanStatus={"scanning": self.scanning, "count": 0})
        if action == "search3":
            offset, size = int(params["songOffset"]), int(params["songCount"])
            return self._ok(searchResult3={"song": self.songs[offset : offset + size]})
        if action == "getPlaylists":
            return self._ok(playlists={"playlist": self.playlists})
        if action == "getSong":
            song = next((s for s in self.songs if s["id"] == params["id"]), None)
            if song is None:
                return httpx.Response(
                    200,
                    json={
                        "subsonic-response": {
                            "status": "failed",
                            "serverVersion": self.version,
                            "error": {"code": 70, "message": "not found"},
                        }
                    },
                )
            return self._ok(song=song)
        raise AssertionError(f"unexpected Navidrome call {action}")

    def client(self, settings=None):
        return NavidromeClient(settings or _settings(), transport=httpx.MockTransport(self.handler))


def _reconciler(server, **settings):
    configured = _settings(**settings)
    return NavidromeIdReconciler(settings=configured, client_factory=lambda: server.client(configured))


def _song(db, relative, **values):
    song = Song(path=f"{MUSIC}/{relative}", filename=relative.rsplit("/", 1)[-1], **values)
    db.add(song)
    db.commit()
    db.refresh(song)
    return song


def _remote(song_id, path, **values):
    return {"id": song_id, "path": path, "isDir": False, **values}


def _state(db):
    row = db.get(AppSetting, STATE_KEY)
    return json.loads(row.value) if row else None


def test_server_version_parsing_and_id_scheme():
    assert parse_server_version("0.64.0") == (0, 64, 0)
    assert parse_server_version("v0.63.2 (abc123)") == (0, 63, 2)
    assert parse_server_version("1.0") == (1, 0, 0)
    assert parse_server_version("dev") is None
    assert navidrome_id_scheme("0.63.9") == "legacy"
    assert navidrome_id_scheme("0.64.0") == "canonical_base62"
    assert navidrome_id_scheme("0.70.1") == "canonical_base62"
    assert navidrome_id_scheme(None) is None


def test_status_reports_id_scheme():
    status = asyncio.run(FakeNavidrome(version="0.64.1").client().status())
    assert status["server_version"] == "0.64.1"
    assert status["id_scheme"] == "canonical_base62"


def test_remote_path_normalization_matches_harmony_paths():
    local = normalize_library_path(f"{MUSIC}/Artist/Album/01 - Song.flac", MUSIC)
    assert local == "artist/album/01 - song.flac"
    assert normalize_library_path("1:Artist/Album/1-01 - Song.flac", MUSIC, remote=True) != local
    assert normalize_library_path("1:Artist/Album/01-01 - Song.flac", MUSIC, remote=True) == local
    assert normalize_library_path("music/Artist/Album/01 - Song.flac", MUSIC, remote=True) == local
    assert normalize_library_path("../etc/passwd", MUSIC, remote=True) == ""


def test_song_id_change_is_remapped_by_path_without_duplicate_records():
    db = SessionLocal()
    try:
        song = _song(
            db,
            "Artist/Album/01 - Song.flac",
            title="Song",
            artist="Artist",
            album="Album",
            navidrome_id="legacy-md5-1",
            spotify_track_id="spotify-1",
        )
        db.add(SongSourceIdentity(provider="spotify", item_id="spotify-1", song_id=song.id))
        db.commit()
        server = FakeNavidrome(songs=[_remote("6xF3d9kLmN2pQrS7tUvW1a", "Artist/Album/01 - Song.flac")])

        result = asyncio.run(_reconciler(server).reconcile())

        assert result["state"] == "completed"
        assert result["songs"]["updated"] == 1
        assert result["songs"]["matched_by"] == {"path": 1}
        db.expire_all()
        assert db.scalar(select(func.count(Song.id))) == 1
        refreshed = db.get(Song, song.id)
        assert refreshed.navidrome_id == "6xF3d9kLmN2pQrS7tUvW1a"
        assert refreshed.spotify_track_id == "spotify-1"
        assert db.scalar(select(SongSourceIdentity.song_id)) == song.id
        assert _state(db)["id_scheme"] == "canonical_base62"
    finally:
        db.close()


def test_playlist_id_change_is_remapped_by_m3u_name():
    db = SessionLocal()
    try:
        playlist = Playlist(spotify_id="playlist-1", name="Road: Trip", navidrome_playlist_id="legacy-pl")
        other = Playlist(spotify_id="playlist-2", name="Unknown", navidrome_playlist_id=None)
        db.add_all([playlist, other])
        db.commit()
        server = FakeNavidrome(playlists=[{"id": "1nWpN0ZqYV2a9fGb3hJk4L", "name": "Road_ Trip"}])

        result = asyncio.run(_reconciler(server).reconcile())

        assert result["playlists"] == {"checked": 2, "unchanged": 0, "updated": 1, "unresolved": 0, "skipped": 1}
        db.expire_all()
        assert db.scalar(select(func.count(Playlist.id))) == 2
        assert db.get(Playlist, playlist.id).navidrome_playlist_id == "1nWpN0ZqYV2a9fGb3hJk4L"
        assert db.get(Playlist, other.id).navidrome_playlist_id is None
    finally:
        db.close()


def test_valid_ids_are_kept_and_swapped_ids_respect_unique_indexes():
    db = SessionLocal()
    try:
        kept = _song(db, "A/A/01 - Kept.mp3", navidrome_id="kept")
        first = _song(db, "A/A/02 - First.mp3", navidrome_id="old-first")
        second = _song(db, "A/A/03 - Second.mp3", navidrome_id="old-second")
        # Navidrome now reports each of these songs under the other's old ID.
        server = FakeNavidrome(
            songs=[
                _remote("kept", "A/A/01 - Kept.mp3"),
                _remote("old-second", "A/A/02 - First.mp3"),
                _remote("old-first", "A/A/03 - Second.mp3"),
            ]
        )

        result = asyncio.run(_reconciler(server).reconcile())

        assert result["songs"]["unchanged"] == 1
        assert result["songs"]["updated"] == 2
        db.expire_all()
        assert db.get(Song, kept.id).navidrome_id == "kept"
        assert db.get(Song, first.id).navidrome_id == "old-second"
        assert db.get(Song, second.id).navidrome_id == "old-first"
    finally:
        db.close()


def test_stable_identifiers_resolve_songs_when_paths_differ():
    db = SessionLocal()
    try:
        by_mbid = _song(db, "X/X/01 - One.mp3", musicbrainz_recording_id="MBID-1", title="One", artist="X")
        by_isrc = _song(db, "X/X/02 - Two.mp3", isrc="usabc2400001", title="Two", artist="X")
        by_metadata = _song(db, "X/X/03 - Three.mp3", title="Three", artist="X", album="Y", duration=200.4)
        wrong_duration = _song(db, "X/X/04 - Four.mp3", title="Four", artist="X", album="Y", duration=100)
        ambiguous = _song(db, "X/X/05 - Five.mp3", isrc="DUP000000001", navidrome_id="stale-5")
        # Navidrome reports synthesized paths that do not match Harmony's files.
        server = FakeNavidrome(
            songs=[
                _remote("n1", "fake/1.mp3", musicBrainzId="mbid-1"),
                _remote("n2", "fake/2.mp3", isrc=["USABC2400001"]),
                _remote("n3", "fake/3.mp3", title="three", artist="x", album="y", duration=201),
                _remote("n4", "fake/4.mp3", title="Four", artist="X", album="Y", duration=180),
                _remote("n5a", "fake/5a.mp3", isrc="DUP000000001"),
                _remote("n5b", "fake/5b.mp3", isrc="DUP000000001"),
            ]
        )

        result = asyncio.run(_reconciler(server).reconcile())

        assert result["songs"]["matched_by"] == {"musicbrainz": 1, "isrc": 1, "metadata": 1}
        assert result["songs"]["unresolved"] == 1
        assert result["songs"]["skipped"] == 1
        db.expire_all()
        assert db.get(Song, by_mbid.id).navidrome_id == "n1"
        assert db.get(Song, by_isrc.id).navidrome_id == "n2"
        assert db.get(Song, by_metadata.id).navidrome_id == "n3"
        assert db.get(Song, wrong_duration.id).navidrome_id is None
        assert db.get(Song, ambiguous.id).navidrome_id is None
    finally:
        db.close()


def test_unresolvable_items_fail_safely_and_remain_recoverable():
    db = SessionLocal()
    try:
        song = _song(db, "Late/Album/01 - Late.mp3", title="Late", navidrome_id="legacy-late")
        server = FakeNavidrome(songs=[])
        reconciler = _reconciler(server)

        first = asyncio.run(reconciler.reconcile())

        assert first["songs"]["unresolved"] == 1
        db.expire_all()
        assert db.get(Song, song.id).navidrome_id is None
        assert db.get(Song, song.id).title == "Late"

        server.songs = [_remote("canonical-late", "Late/Album/01 - Late.mp3")]
        second = asyncio.run(reconciler.reconcile())

        assert second["songs"]["updated"] == 1
        db.expire_all()
        assert db.get(Song, song.id).navidrome_id == "canonical-late"
    finally:
        db.close()


@pytest.mark.parametrize("scanning, reachable", [(True, True), (False, False)])
def test_reconcile_changes_nothing_while_navidrome_is_scanning_or_offline(scanning, reachable):
    db = SessionLocal()
    try:
        song = _song(db, "A/B/01 - C.mp3", navidrome_id="legacy")
        server = FakeNavidrome(scanning=scanning, songs=[])
        reconciler = _reconciler(server)
        if not reachable:
            def offline(request):
                raise httpx.ConnectError("refused", request=request)

            reconciler.client_factory = lambda: NavidromeClient(_settings(), transport=httpx.MockTransport(offline))

        result = asyncio.run(reconciler.reconcile())

        assert result["state"] == ("scanning" if reachable else "unavailable")
        assert "search3" not in server.calls
        db.expire_all()
        assert db.get(Song, song.id).navidrome_id == "legacy"
        assert _state(db) is None
    finally:
        db.close()


def test_pre_064_server_is_left_unaffected():
    db = SessionLocal()
    try:
        song = _song(db, "A/B/01 - C.mp3", navidrome_id="legacy-1")
        server = FakeNavidrome(version="0.58.0", songs=[_remote("legacy-1", "A/B/01 - C.mp3")])

        assert asyncio.run(_reconciler(server).reconcile_if_needed()) is None

        assert "search3" not in server.calls
        db.expire_all()
        assert db.get(Song, song.id).navidrome_id == "legacy-1"
        assert _state(db) == {"server_version": "0.58.0", "id_scheme": "legacy"}

        server.calls.clear()
        assert asyncio.run(_reconciler(server).reconcile_if_needed()) is None
        assert server.calls == ["getScanStatus"]
    finally:
        db.close()


def test_upgrade_to_064_triggers_one_automatic_reconciliation():
    db = SessionLocal()
    try:
        db.add(
            AppSetting(
                key=STATE_KEY,
                value=json.dumps({"server_version": "0.63.1", "id_scheme": "legacy"}),
                type="json",
                category="internal",
            )
        )
        db.commit()
        song = _song(db, "A/B/01 - C.mp3", navidrome_id="legacy-1")
        server = FakeNavidrome(version="0.64.0", songs=[_remote("Zx81", "A/B/01 - C.mp3")])
        reconciler = _reconciler(server)

        result = asyncio.run(reconciler.reconcile_if_needed())

        assert result["trigger"] == "automatic"
        assert result["songs"]["updated"] == 1
        db.expire_all()
        assert db.get(Song, song.id).navidrome_id == "Zx81"

        server.calls.clear()
        assert asyncio.run(reconciler.reconcile_if_needed()) is None
        assert "search3" not in server.calls
    finally:
        db.close()


def test_future_version_with_unresolvable_ids_triggers_reconciliation():
    db = SessionLocal()
    try:
        db.add(
            AppSetting(
                key=STATE_KEY,
                value=json.dumps({"server_version": "0.64.0", "id_scheme": "canonical_base62"}),
                type="json",
                category="internal",
            )
        )
        db.commit()
        song = _song(db, "A/B/01 - C.mp3", navidrome_id="old-canonical")
        server = FakeNavidrome(version="0.70.0", songs=[_remote("new-canonical", "A/B/01 - C.mp3")])

        result = asyncio.run(_reconciler(server).reconcile_if_needed())

        assert "getSong" in server.calls
        assert result["songs"]["updated"] == 1
        db.expire_all()
        assert db.get(Song, song.id).navidrome_id == "new-canonical"
    finally:
        db.close()


def test_version_change_with_resolvable_ids_only_records_version():
    db = SessionLocal()
    try:
        db.add(
            AppSetting(
                key=STATE_KEY,
                value=json.dumps({"server_version": "0.64.0", "id_scheme": "canonical_base62"}),
                type="json",
                category="internal",
            )
        )
        db.commit()
        _song(db, "A/B/01 - C.mp3", navidrome_id="stable")
        server = FakeNavidrome(version="0.64.1", songs=[_remote("stable", "A/B/01 - C.mp3")])

        assert asyncio.run(_reconciler(server).reconcile_if_needed()) is None
        assert "search3" not in server.calls
        db.expire_all()
        assert _state(db)["server_version"] == "0.64.1"
    finally:
        db.close()


def test_m3u_export_succeeds_with_stale_navidrome_ids(monkeypatch, tmp_path):
    monkeypatch.setattr(playlist_manager, "get_settings", lambda: SimpleNamespace(music_path=str(tmp_path)))
    audio = tmp_path / "Artist" / "Album" / "01 - Song.mp3"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"audio")
    db = SessionLocal()
    try:
        db.add(
            Song(
                path=str(audio),
                filename=audio.name,
                artist="Artist",
                title="Song",
                duration=180,
                spotify_track_id="track-1",
                navidrome_id="stale-legacy-id",
            )
        )
        playlist = Playlist(spotify_id="playlist-1", name="Stale", navidrome_playlist_id="stale-playlist")
        playlist.tracks.append(PlaylistTrack(spotify_track_id="track-1", position=0, title="Song", artist="Artist"))
        db.add(playlist)
        db.commit()

        assert playlist_manager.export_m3u(db, playlist) == 1
        assert "../Artist/Album/01 - Song.mp3" in (tmp_path / "Playlists" / "Stale.m3u").read_text()
    finally:
        db.close()


def test_coordinator_checks_ids_after_playlist_reconciliation(monkeypatch):
    from app.services import navidrome_playlist_sync
    from app.services.navidrome_playlist_sync import NavidromePlaylistReimportCoordinator

    checked = []

    class Reconciler:
        async def reconcile_if_needed(self, client):
            checked.append(client)

    class Client:
        statuses = iter([False, True, False, False, True, False])

        async def status(self):
            return {"reachable": True, "scanning": next(self.statuses), "last_scan": None}

        async def start_scan(self, *, full_scan=False):
            return {"accepted": True, "scanning": True}

    monkeypatch.setattr(navidrome_playlist_sync, "export_m3u", lambda db, playlist: 0)
    coordinator = NavidromePlaylistReimportCoordinator(
        settings=SimpleNamespace(
            navidrome_url="http://navidrome:4533",
            navidrome_username="harmony",
            navidrome_password="secret",
            navidrome_playlist_reimport_enabled=True,
            navidrome_playlist_reimport_debounce_seconds=0,
            navidrome_playlist_reimport_poll_seconds=0.01,
            navidrome_playlist_reimport_scan_timeout_seconds=2,
        ),
        client_factory=Client,
        id_reconciler=Reconciler(),
    )
    monkeypatch.setattr(coordinator, "_playlist_ids", lambda task_ids: [1])
    monkeypatch.setattr(coordinator, "_rewrite_playlists", lambda ids: 1)

    assert asyncio.run(coordinator.reconcile({1})) is True
    assert len(checked) == 1 and isinstance(checked[0], Client)


def test_manual_api_returns_summary_and_clean_errors(monkeypatch):
    class Reconciler:
        def __init__(self, result):
            self.result = result

        async def reconcile(self, *, trigger):
            assert trigger == "manual"
            return self.result

    monkeypatch.setattr(navidrome_api, "navidrome_id_reconciler", Reconciler({"state": "completed", "songs": {}}))
    assert asyncio.run(navidrome_api.reconcile_navidrome_ids())["state"] == "completed"

    monkeypatch.setattr(navidrome_api, "navidrome_id_reconciler", Reconciler({"state": "scanning"}))
    with pytest.raises(HTTPException) as error:
        asyncio.run(navidrome_api.reconcile_navidrome_ids())
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "navidrome_ids_scanning"


def test_reconciliation_state_is_not_exported_or_imported_as_a_setting():
    db = SessionLocal()
    try:
        db.add(AppSetting(key=STATE_KEY, value="{}", type="json", category="internal"))
        db.commit()
        assert STATE_KEY not in {item["key"] for item in export_settings(db)["settings"]}

        db.delete(db.get(AppSetting, STATE_KEY))
        db.commit()
        import_settings(
            db,
            {
                "format": "harmony-settings",
                "version": 1,
                "settings": [{"key": STATE_KEY, "value": "{}", "type": "json", "category": "internal"}],
            },
        )
        assert db.get(AppSetting, STATE_KEY) is None
    finally:
        db.close()

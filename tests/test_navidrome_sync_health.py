import asyncio
from types import SimpleNamespace

from sqlalchemy import select

from app.database.models import Playlist, Song
from app.database.session import SessionLocal
from app.services.navidrome_sync_health import (
    NavidromeSyncHealth,
    normalize_library_path,
)
from app.services.library_paths import sanitize_path_component


class FakeNavidrome:
    configured = True

    def __init__(self, *, stale=False):
        self.stale = stale
        self.scan_requests = 0

    async def library_songs(self):
        songs = [{"id": "remote-1", "path": "Artist/Album/song.mp3"}]
        if self.stale:
            songs.append({"id": "stale", "path": "removed.mp3"})
        return songs

    async def get_albums(self):
        return [{"id": "album-1"}]

    async def get_artists(self):
        return [{"id": "artist-1"}]

    async def get_playlists(self):
        return [{"id": "playlist-1", "name": "Favourites"}]

    async def status(self):
        return {"reachable": True, "scanning": False}

    async def start_scan(self):
        self.scan_requests += 1


class BrokenNavidrome(FakeNavidrome):
    async def library_songs(self):
        raise RuntimeError("unexpected response shape")


def settings(*, auto_reconcile=False):
    return SimpleNamespace(
        music_path="/music",
        navidrome_sync_health_auto_reconcile=auto_reconcile,
        navidrome_sync_health_enabled=True,
        navidrome_sync_health_interval_minutes=15,
    )


def seed_library():
    db = SessionLocal()
    try:
        db.add(
            Song(
                path="/music/Artist/Album/song.mp3",
                filename="song.mp3",
                artist="Artist",
                album="Album",
            )
        )
        db.add(Playlist(spotify_id="playlist", name="Favourites"))
        db.commit()
    finally:
        db.close()


def test_sync_health_reports_matching_library_counts(monkeypatch):
    monkeypatch.setattr(
        "app.services.navidrome_sync_health.os.path.isfile", lambda _: True
    )
    monkeypatch.setattr("app.services.navidrome_sync_health.os.access", lambda *_: True)
    seed_library()
    health = NavidromeSyncHealth(settings=settings(), client=FakeNavidrome())

    result = asyncio.run(health.check())

    assert result["state"] == "healthy"
    assert (
        result["expected"]
        == result["actual"]
        == {"songs": 1, "albums": 1, "artists": 1, "playlists": 1}
    )
    assert result["missing_tracks"] == 0
    assert result["stale_tracks"] == 0


def test_sync_health_requests_reconciliation_when_drift_is_detected():
    seed_library()
    client = FakeNavidrome(stale=True)
    health = NavidromeSyncHealth(settings=settings(auto_reconcile=True), client=client)

    result = asyncio.run(health.check())

    assert result["state"] == "drift"
    assert result["stale_tracks"] == 1
    assert result["reconciliation_requested"] is True
    assert client.scan_requests == 1


def test_sync_health_returns_clean_unavailable_state_for_unexpected_failures():
    health = NavidromeSyncHealth(settings=settings(), client=BrokenNavidrome())

    result = asyncio.run(health.check())

    assert result["state"] == "unavailable"
    assert result["error"] == "unexpected response shape"
    assert health._lock.acquire(blocking=False) is True
    health._lock.release()


def test_path_normalization_is_lexical_and_library_relative():
    assert (
        normalize_library_path("Artist/Album/song.mp3", "/music")
        == "artist/album/song.mp3"
    )
    assert (
        normalize_library_path("/music/Artist/Album/song.mp3", "/music")
        == "artist/album/song.mp3"
    )
    assert (
        normalize_library_path("/volume1/music/Artist/Album/song.mp3", "/music")
        == "artist/album/song.mp3"
    )
    assert (
        normalize_library_path(r"C:\\music\\Artist\\Album\\song.mp3", "/music")
        == "artist/album/song.mp3"
    )
    assert normalize_library_path(
        "Artist/Cafe%CC%81/song.mp3", "/music"
    ) == normalize_library_path("Artist/Caf%C3%A9/song.mp3", "/music")
    assert (
        normalize_library_path(
            "1:Gajendra Verma/Table No. 21/02 - Mann Mera.mp3",
            "/music",
            remote=True,
        )
        == "gajendra verma/table no. 21/02 - mann mera.mp3"
    )
    # Metadata punctuation is sanitized, while non-numeric prefixes are not
    # mistaken for Navidrome's music-folder namespace.
    assert normalize_library_path("Artist/12: Song.mp3", "/music", remote=True) == (
        "artist/12_ song.mp3"
    )
    assert normalize_library_path("folder:Artist/song.mp3", "/music", remote=True) == (
        "folder_artist/song.mp3"
    )


def test_disc_track_prefix_is_equivalent_to_track_prefix_only_in_filename():
    assert normalize_library_path(
        "/music/Artist/Album/02 - Song.mp3", "/music"
    ) == normalize_library_path(
        "Artist/Album/01-02 - Song.mp3", "/music", remote=True
    )
    assert normalize_library_path(
        "/music/Artist_Name/Album/02 - Song.mp3", "/music"
    ) == normalize_library_path(
        "Artist|Name/Album/01-02 - Song.mp3", "/music", remote=True
    )


def test_remote_metadata_punctuation_is_sanitized_in_directories_and_basenames():
    examples = (
        (
            "Long Distance Love | Coke Studio Bharat",
            "Long Distance Love _ Coke Studio Bharat",
        ),
        ('Psycho Saiyaan (From "Saaho")', "Psycho Saiyaan (From _Saaho_)"),
        ("Spider-Man: Into the Spider-Verse", "Spider-Man_ Into the Spider-Verse"),
    )
    for remote_name, local_name in examples:
        local = f"/music/{local_name}/{local_name}/01 - {local_name}.mp3"
        remote = f"{remote_name}/{remote_name}/01-01 - {remote_name}.mp3"
        assert normalize_library_path(local, "/music") == normalize_library_path(
            remote, "/music", remote=True
        )


def test_canonical_sanitizer_is_idempotent_unicode_safe_and_blocks_separators():
    value = ' বাংলা / ..\\Spider-Man: "Song" | Mix?* '
    sanitized = sanitize_path_component(value)
    assert sanitized == 'বাংলা _ .._Spider-Man_ _Song_ _ Mix__'
    assert sanitize_path_component(sanitized) == sanitized
    assert "/" not in sanitized and "\\" not in sanitized
    assert sanitize_path_component(".") == "_"
    assert sanitize_path_component("..") == "_"


def test_remote_sanitization_remains_directory_strict_and_not_fuzzy():
    local = "/music/Artist/Album_Name/01 - Song_Name.mp3"
    assert normalize_library_path(local, "/music") == normalize_library_path(
        "Artist/Album|Name/01-01 - Song|Name.mp3", "/music", remote=True
    )
    assert normalize_library_path(local, "/music") != normalize_library_path(
        "Artist/Other|Album/01-01 - Song|Name.mp3", "/music", remote=True
    )
    assert normalize_library_path(local, "/music") != normalize_library_path(
        "Artist/Album-Name/01-01 - Song-Name.mp3", "/music", remote=True
    )


def test_encoded_slash_and_traversal_cannot_masquerade_as_safe_component():
    safe = normalize_library_path(
        "/music/Artist/Album_Name/01 - Song.mp3", "/music"
    )
    assert safe != normalize_library_path(
        "Artist/Album%2FName/01-01 - Song.mp3", "/music", remote=True
    )
    assert safe != normalize_library_path(
        "Artist/ignored/../Album_Name/01-01 - Song.mp3", "/music", remote=True
    )
    assert normalize_library_path(
        "/music/Artist/01-02 - Album/02 - Song.mp3", "/music"
    ) != normalize_library_path(
        "Artist/02 - Album/01-02 - Song.mp3", "/music", remote=True
    )


def test_production_disc_track_prefix_restores_one_to_one_path_matches():
    local_paths = [
        f"/music/Artist/Album/{index % 100:02d} - Song {index}.mp3"
        for index in range(1794)
    ]
    remote = [
        {
            "id": f"remote-{index}",
            "path": f"Artist/Album/01-{index % 100:02d} - Song {index}.mp3",
        }
        for index in range(1782)
    ]
    normalized_remote_paths = {
        normalize_library_path(item["path"], "/music", remote=True)
        for item in remote
    }
    matches = sum(
        normalize_library_path(path, "/music") in normalized_remote_paths
        for path in local_paths
    )

    assert matches == 1782
    assert (len(local_paths) - matches, len(remote) - matches) == (12, 0)


def test_production_scale_sanitized_health_regression(monkeypatch):
    local_songs = [
        SimpleNamespace(
            id=index,
            path=f"/music/Artist/Album_Name/{index % 100:02d} - Song {index}.mp3",
            navidrome_id=None,
            file_exists=index >= 12,
            title=f"Song {index}",
            album="Album_Name",
            artist="Artist",
        )
        for index in range(1794)
    ]
    remote_songs = [
        {
            "id": f"remote-{index}",
            "path": f"Artist/Album|Name/01-{index % 100:02d} - Song {index}.mp3",
        }
        for index in range(1782)
    ]
    client = FakeNavidrome()
    client.library_songs = lambda: asyncio.sleep(0, result=remote_songs)
    client.get_playlists = lambda: asyncio.sleep(0, result=[])
    health = NavidromeSyncHealth(settings=settings(), client=client)
    monkeypatch.setattr(
        health,
        "_read_local",
        lambda: (
            local_songs,
            [],
            {"songs": 1794, "albums": 1, "artists": 1, "playlists": 0},
        ),
    )

    result = asyncio.run(health.check())

    assert result["expected"]["songs"] == 1794
    assert result["missing_on_filesystem"] == 12
    assert result["actual"]["songs"] == 1782
    assert result["recovered_by_path"] == 1782
    assert result["missing_tracks"] == 12
    assert result["stale_tracks"] == 0
    assert result["ambiguous_matches"] == 0


def test_stored_id_accepts_canonical_sanitization(monkeypatch):
    seed_library()
    db = SessionLocal()
    try:
        song = db.scalar(select(Song))
        song.path = "/music/Artist/Album_Name/01 - Song_Name.mp3"
        song.filename = "01 - Song_Name.mp3"
        song.navidrome_id = "remote-1"
        db.commit()
    finally:
        db.close()
    client = FakeNavidrome()
    client.library_songs = lambda: asyncio.sleep(
        0,
        result=[
            {
                "id": "remote-1",
                "path": "Artist/Album|Name/01-01 - Song:Name.mp3",
            }
        ],
    )
    monkeypatch.setattr(
        "app.services.navidrome_sync_health.os.path.isfile", lambda _: True
    )
    monkeypatch.setattr("app.services.navidrome_sync_health.os.access", lambda *_: True)

    result = asyncio.run(NavidromeSyncHealth(settings=settings(), client=client).check())

    assert result["inconsistent_stored_navidrome_id"] == 0
    assert result["missing_tracks"] == result["stale_tracks"] == 0


def test_stored_id_accepts_disc_track_prefix_but_rejects_other_path_drift(monkeypatch):
    seed_library()
    db = SessionLocal()
    try:
        song = db.scalar(select(Song))
        song.path = "/music/Artist/Album/02 - Song.mp3"
        song.filename = "02 - Song.mp3"
        song.navidrome_id = "remote-1"
        db.commit()
    finally:
        db.close()
    client = FakeNavidrome()

    async def disc_track_song():
        return [{"id": "remote-1", "path": "Artist/Album/01-02 - Song.mp3"}]

    client.library_songs = disc_track_song
    monkeypatch.setattr(
        "app.services.navidrome_sync_health.os.path.isfile", lambda _: True
    )
    monkeypatch.setattr("app.services.navidrome_sync_health.os.access", lambda *_: True)

    matched = asyncio.run(
        NavidromeSyncHealth(settings=settings(), client=client).check()
    )
    assert matched["missing_tracks"] == matched["stale_tracks"] == 0
    assert matched["inconsistent_stored_navidrome_id"] == 0

    async def drifted_directory_song():
        return [{"id": "remote-1", "path": "Artist|Name/Album/01-02 - Song.mp3"}]

    client.library_songs = drifted_directory_song
    rejected = asyncio.run(
        NavidromeSyncHealth(settings=settings(), client=client).check()
    )
    assert rejected["missing_tracks"] == rejected["stale_tracks"] == 1
    assert rejected["inconsistent_stored_navidrome_id"] == 1


def test_stale_id_is_recovered_and_persisted(monkeypatch):
    seed_library()
    db = SessionLocal()
    try:
        song = db.scalar(select(Song))
        song.navidrome_id = "old-id"
        db.commit()
    finally:
        db.close()
    monkeypatch.setattr(
        "app.services.navidrome_sync_health.os.path.isfile", lambda _: True
    )
    monkeypatch.setattr("app.services.navidrome_sync_health.os.access", lambda *_: True)
    result = asyncio.run(
        NavidromeSyncHealth(settings=settings(), client=FakeNavidrome()).check(
            repair_ids=True
        )
    )
    assert result["invalid_stored_navidrome_id"] == 1
    assert result["recovered_by_path"] == result["repaired_navidrome_ids"] == 1
    db = SessionLocal()
    try:
        assert db.scalar(select(Song.navidrome_id)) == "remote-1"
    finally:
        db.close()


def test_missing_file_is_separate_from_missing_in_navidrome():
    seed_library()
    result = asyncio.run(
        NavidromeSyncHealth(settings=settings(), client=FakeNavidrome()).check()
    )
    assert result["missing_on_filesystem"] == 1
    assert result["missing_from_navidrome"] == 0


def test_duplicate_remote_path_is_ambiguous_and_not_repaired(monkeypatch):
    seed_library()
    db = SessionLocal()
    try:
        song = db.scalar(select(Song))
        song.path = "/music/Artist/Album/song_name.mp3"
        song.filename = "song_name.mp3"
        db.commit()
    finally:
        db.close()
    client = FakeNavidrome()

    async def duplicates():
        return [
            {"id": "one", "path": "Artist/Album/song|name.mp3"},
            {"id": "two", "path": "Artist/Album/song:name.mp3"},
        ]

    client.library_songs = duplicates
    monkeypatch.setattr(
        "app.services.navidrome_sync_health.os.path.isfile", lambda _: True
    )
    monkeypatch.setattr("app.services.navidrome_sync_health.os.access", lambda *_: True)
    result = asyncio.run(
        NavidromeSyncHealth(settings=settings(), client=client).check(repair_ids=True)
    )
    assert result["ambiguous_matches"] == 1
    assert result["duplicate_remote_paths"] == 1
    assert result["repaired_navidrome_ids"] == 0
    assert result["duplicate_remote_path_samples"] == [
        {
            "normalized_path": "artist/album/song_name.mp3",
            "raw_paths": [
                "Artist/Album/song|name.mp3",
                "Artist/Album/song:name.mp3",
            ],
        }
    ]

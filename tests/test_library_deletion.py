import errno
from pathlib import Path

import pytest

from app.services import library_service


def test_delete_only_song_prunes_album_and_nested_artist(tmp_path):
    music = tmp_path / "music"
    album = music / "Artist" / "Nested" / "Album"
    album.mkdir(parents=True)
    song = album / "song.mp3"
    song.write_bytes(b"audio")

    library_service.delete_library_file(song, music)

    assert not album.exists()
    assert not (music / "Artist").exists()
    assert music.is_dir()


def test_pruning_stops_at_and_never_removes_music_root(tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    song = music / "song.mp3"
    song.write_bytes(b"audio")

    library_service.delete_library_file(song, music)

    assert music.is_dir()


def test_artist_remains_when_another_album_contains_a_song(tmp_path):
    music = tmp_path / "music"
    deleted_album = music / "Artist" / "Deleted Album"
    kept_album = music / "Artist" / "Kept Album"
    deleted_album.mkdir(parents=True)
    kept_album.mkdir()
    deleted_song = deleted_album / "song.mp3"
    kept_song = kept_album / "other.mp3"
    deleted_song.write_bytes(b"audio")
    kept_song.write_bytes(b"audio")

    library_service.delete_library_file(deleted_song, music)

    assert not deleted_album.exists()
    assert kept_song.is_file()
    assert (music / "Artist").is_dir()


def test_album_remains_when_any_other_file_is_present(tmp_path):
    music = tmp_path / "music"
    album = music / "Artist" / "Album"
    album.mkdir(parents=True)
    song = album / "song.mp3"
    artwork = album / "cover.jpg"
    song.write_bytes(b"audio")
    artwork.write_bytes(b"artwork")

    library_service.delete_library_file(song, music)

    assert album.is_dir()
    assert artwork.is_file()


def test_symlink_to_outside_music_root_is_rejected(tmp_path):
    music = tmp_path / "music"
    outside = tmp_path / "outside"
    music.mkdir()
    outside.mkdir()
    outside_song = outside / "song.mp3"
    outside_song.write_bytes(b"audio")
    (music / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="configured music folder"):
        library_service.delete_library_file(music / "escape" / "song.mp3", music)

    assert outside_song.is_file()
    assert outside.is_dir()


def test_concurrent_nonempty_rmdir_failure_stops_safely(tmp_path, monkeypatch):
    music = tmp_path / "music"
    album = music / "Artist" / "Album"
    album.mkdir(parents=True)
    deleted_song = album / "song.mp3"
    deleted_song.write_bytes(b"audio")
    real_rmdir = Path.rmdir

    def became_nonempty(path):
        if path == album:
            (album / "concurrent.mp3").write_bytes(b"new")
            raise OSError(errno.ENOTEMPTY, "Directory not empty", str(path))
        return real_rmdir(path)

    monkeypatch.setattr(Path, "rmdir", became_nonempty)
    library_service.delete_library_file(deleted_song, music)

    assert (album / "concurrent.mp3").is_file()
    assert (music / "Artist").is_dir()


def test_cleanup_error_does_not_fail_successful_song_deletion(tmp_path, monkeypatch):
    music = tmp_path / "music"
    album = music / "Artist" / "Album"
    album.mkdir(parents=True)
    song = album / "song.mp3"
    song.write_bytes(b"audio")

    monkeypatch.setattr(
        Path,
        "rmdir",
        lambda path: (_ for _ in ()).throw(PermissionError("read-only directory")),
    )

    assert library_service.delete_library_file(song, music) == song.resolve()
    assert not song.exists()
    assert album.is_dir()

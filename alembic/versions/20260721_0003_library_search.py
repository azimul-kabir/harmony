"""Add the FTS5 projection for indexed Library search."""

from alembic import op
import sqlalchemy as sa

revision = "20260721_0003"
down_revision = "20260721_0002"
branch_labels = None
depends_on = None


CREATE_SEARCH_INDEX = """
CREATE VIRTUAL TABLE IF NOT EXISTS library_search USING fts5(
    song_id UNINDEXED,
    title,
    artist,
    album,
    genre,
    playlist,
    filename,
    spotify_id,
    musicbrainz_id,
    isrc,
    tokenize = 'unicode61 remove_diacritics 2'
)
"""


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(CREATE_SEARCH_INDEX)
    connection.exec_driver_sql("DELETE FROM library_search")
    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())
    song_columns = {column["name"] for column in inspector.get_columns("songs")}

    def song_value(column: str) -> str:
        return f"coalesce(songs.{column}, '')" if column in song_columns else "''"

    if {"playlists", "playlist_tracks"} <= tables and "spotify_track_id" in song_columns:
        playlist_value = """coalesce((
            SELECT group_concat(playlists.name, ' ')
            FROM playlist_tracks
            JOIN playlists ON playlists.id = playlist_tracks.playlist_id
            WHERE playlist_tracks.spotify_track_id = songs.spotify_track_id
        ), '')"""
    else:
        playlist_value = "''"

    connection.exec_driver_sql(
        f"""
        INSERT INTO library_search (
            song_id, title, artist, album, genre, playlist, filename,
            spotify_id, musicbrainz_id, isrc
        )
        SELECT
            songs.id,
            {song_value('title')},
            {song_value('artist')},
            {song_value('album')},
            {song_value('genre')},
            {playlist_value},
            {song_value('filename')},
            {song_value('spotify_track_id')},
            {song_value('musicbrainz_recording_id')},
            {song_value('isrc')}
        FROM songs
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS library_search")

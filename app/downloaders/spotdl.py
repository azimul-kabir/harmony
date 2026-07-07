stdout = subprocess.run(...)

songs = json.loads(...)

validated = [
    SpotDLSong.model_validate(song)
    for song in songs
]

tracks = [
    spotdl_song_to_track(song)
    for song in validated
]
from app.services.library_events import LibraryEventBroker


def test_library_event_broker_fans_out_events():
    broker = LibraryEventBroker()
    first = broker.subscribe()
    second = broker.subscribe()

    event = broker.publish("library.track.added", song_id=42)

    assert first.get_nowait() == event
    assert second.get_nowait() == event
    assert event.payload == {"song_id": 42}

    broker.unsubscribe(first)
    broker.unsubscribe(second)

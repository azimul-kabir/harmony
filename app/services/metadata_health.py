"""Rule-based metadata diagnostics.  Rules only inspect the library index."""
from __future__ import annotations
import hashlib, json, re, unicodedata
from collections import Counter
from datetime import datetime
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.core.time import utcnow_naive
from app.database.models import MetadataIssue, Song

RULES = {
    **{name: {"severity": "warning", "scope": "song"} for name in ("missing_title missing_artist missing_album missing_album_artist missing_track_number missing_year_or_release_date missing_genre missing_artwork placeholder_title placeholder_artist placeholder_album filename_derived_title suspicious_whitespace inconsistent_capitalization").split()},
    **{name: {"severity": "error", "scope": "song"} for name in ("invalid_track_number invalid_disc_number invalid_year zero_or_implausible_duration").split()},
    **{name: {"severity": "info", "scope": "song"} for name in ("missing_isrc missing_musicbrainz_recording_id").split()},
    **{name: {"severity": "warning", "scope": "album"} for name in ("inconsistent_album_artist inconsistent_album_title inconsistent_release_year inconsistent_genre duplicate_track_number missing_track_numbers non_contiguous_track_numbers inconsistent_disc_totals inconsistent_track_totals inconsistent_artwork probable_split_album mixed_album_artist_and_track_artist_without_compilation_marker").split()},
    "missing_musicbrainz_release_id": {"severity":"info", "scope":"album"},
    **{name: {"severity": "warning", "scope": "artist"} for name in ("artist_name_variants suspicious_artist_spacing inconsistent_artist_capitalization").split()},
    "missing_musicbrainz_artist_id": {"severity":"info", "scope":"artist"},
}
PLACEHOLDERS = {"unknown", "untitled", "track", "artist", "album", "n/a", "none"}

def normalize(value: str | None, *, artist: bool = False) -> str | None:
    if value is None: return None
    value = unicodedata.normalize("NFKC", value).strip()
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"[’‘]", "'", value)
    value = re.sub(r"[‐‑–—]", "-", value).casefold()
    # The prefix is comparison-only and does not discard featured artists or versions.
    if artist and value.startswith("the "): value = value[4:]
    return value

class MetadataHealthService:
    @staticmethod
    def album_key(song: Song) -> str:
        """Stable projection identity: normalized album artist + album title."""
        return f"{normalize(song.album_artist or song.artist, artist=True) or ''}::{normalize(song.album) or ''}"

    @staticmethod
    def artist_key(value: str | None) -> str:
        """Stable, conservative artist projection identity; featured tokens remain."""
        return normalize(value, artist=True) or ""
    def _finding(self, rule, entity_type, entity_id, *, field=None, value=None, song=None, album=None, artist=None, evidence=None):
        identity = hashlib.sha256("|".join((rule, entity_type, str(entity_id), field or "", json.dumps(evidence or {}, sort_keys=True))).encode()).hexdigest()
        return {"identity_key":identity, "rule_id":rule, "rule_version":"1", "entity_type":entity_type, "entity_id":str(entity_id), "field_name":field, "current_value":str(value)[:2000] if value is not None else None, "normalized_value":normalize(str(value)) if value else None, "song_id":song.id if song else None, "album_key":album, "artist_key":artist, "severity":RULES[rule]["severity"], "title":rule.replace("_", " ").capitalize(), "explanation":f"Indexed metadata triggered the {rule.replace('_', ' ')} rule.", "suggested_action":"Review the canonical metadata in Harmony.", "automatically_repairable":False, "evidence":json.dumps(evidence or {}, separators=(",", ":"))[:2000]}

    def detect_song(self, song: Song):
        out=[]
        fields={"title":song.title,"artist":song.artist,"album":song.album,"album_artist":song.album_artist,"track_number":song.track,"year_or_release_date":song.year,"genre":song.genre}
        for field, value in fields.items():
            if value is None or (isinstance(value,str) and not value.strip()): out.append(self._finding("missing_"+field,"song",song.id,field=field,value=value,song=song,album=song.album,artist=song.artist))
        for rule, field, value in (("missing_artwork","artwork",song.artwork_id), ("missing_isrc","isrc",song.isrc), ("missing_musicbrainz_recording_id","musicbrainz_recording_id",song.musicbrainz_recording_id)):
            if not value: out.append(self._finding(rule,"song",song.id,field=field,song=song,album=song.album,artist=song.artist))
        for field in ("title","artist","album"):
            value=getattr(song,field)
            if value and normalize(value) in PLACEHOLDERS: out.append(self._finding("placeholder_"+field,"song",song.id,field=field,value=value,song=song))
            if value and value != value.strip() or value and re.search(r"\s{2,}",value): out.append(self._finding("suspicious_whitespace","song",song.id,field=field,value=value,song=song))
        if song.track is not None and song.track <= 0: out.append(self._finding("invalid_track_number","song",song.id,field="track_number",value=song.track,song=song))
        if song.disc is not None and song.disc <= 0: out.append(self._finding("invalid_disc_number","song",song.id,field="disc_number",value=song.disc,song=song))
        if song.year is not None and not 1000 <= song.year <= datetime.now().year + 1: out.append(self._finding("invalid_year","song",song.id,field="year",value=song.year,song=song))
        if song.duration is not None and (song.duration <= 0 or song.duration > 8*3600): out.append(self._finding("zero_or_implausible_duration","song",song.id,field="duration",value=song.duration,song=song))
        return out

    def reconcile(self, db, findings, *, scope=None, job_id=None):
        now=utcnow_naive(); ids={x["identity_key"] for x in findings}
        if scope:
            q=select(MetadataIssue).where(MetadataIssue.entity_type==scope[0], MetadataIssue.entity_id==str(scope[1]))
            for issue in db.scalars(q):
                if issue.identity_key not in ids and issue.status == "open": issue.status="resolved"; issue.resolved_at=now
        for data in findings:
            issue=db.scalar(select(MetadataIssue).where(MetadataIssue.identity_key==data["identity_key"]))
            if issue:
                for k,v in data.items(): setattr(issue,k,v)
                issue.last_detected_at=now; issue.detection_job_id=job_id
                if issue.status == "resolved": issue.status="open"; issue.resolved_at=None
            else: db.add(MetadataIssue(**data, first_detected_at=now,last_detected_at=now,detection_job_id=job_id))

    def analyze_song(self, db, song_id, job_id=None):
        song=db.get(Song,song_id)
        if not song: raise LookupError("Song not found")
        findings=self.detect_song(song); self.reconcile(db,findings,scope=("song",song.id),job_id=job_id); return findings
    def analyze_full(self, db, job_id=None):
        songs=list(db.scalars(select(Song).where(Song.availability_status=="available")).all())
        for song in songs: self.analyze_song(db,song.id,job_id)
        self._analyze_projections(db, songs, job_id)
        return len(songs)

    def _analyze_projections(self, db, songs, job_id=None):
        albums={}; artists={}
        for song in songs:
            if song.album: albums.setdefault(self.album_key(song), []).append(song)
            if song.artist: artists.setdefault(self.artist_key(song.artist), []).append(song)
        for key, rows in albums.items(): self.analyze_album_rows(db, key, rows, job_id)
        for key, rows in artists.items(): self.analyze_artist_rows(db, key, rows, job_id)

    def analyze_album_rows(self, db, key, rows, job_id=None):
        findings=[]; first=rows[0]; values=lambda attr:{normalize(str(getattr(s,attr))) for s in rows if getattr(s,attr) is not None}
        # Different canonical spellings within one projection are suspicious but never rewritten.
        for rule, attr in (("inconsistent_album_artist","album_artist"),("inconsistent_album_title","album"),("inconsistent_release_year","year"),("inconsistent_genre","genre")):
            seen=values(attr)
            if len(seen)>1: findings.append(self._finding(rule,"album",key,field=attr,value=", ".join(sorted(seen)),album=key,evidence={"variants":min(len(seen),20)}))
        tracks=[s.track for s in rows if s.track is not None and s.track>0]
        counts=Counter(tracks)
        if any(v>1 for v in counts.values()): findings.append(self._finding("duplicate_track_number","album",key,field="track_number",album=key,evidence={"duplicates":sorted(k for k,v in counts.items() if v>1)[:20]}))
        if any(s.track is None for s in rows): findings.append(self._finding("missing_track_numbers","album",key,field="track_number",album=key))
        if tracks and len(rows)==len(tracks) and len(set(tracks))==len(tracks) and set(tracks)!=set(range(1,max(tracks)+1)): findings.append(self._finding("non_contiguous_track_numbers","album",key,field="track_number",album=key))
        # Disc numbers are only assessed when a release actually has multiple discs.
        discs={s.disc for s in rows if s.disc and s.disc>0}
        if len(discs)>1 and any(s.disc is None for s in rows): findings.append(self._finding("inconsistent_disc_totals","album",key,field="disc_number",album=key))
        artwork={s.artwork_id for s in rows}
        if len(artwork)>1 and any(artwork): findings.append(self._finding("inconsistent_artwork","album",key,field="artwork",album=key))
        album_artists=values("album_artist")
        track_artists=values("artist")
        compilation=any(normalize(s.album_artist) in {"various artists","various"} for s in rows)
        if len(album_artists)==1 and len(track_artists)>1 and not compilation: findings.append(self._finding("mixed_album_artist_and_track_artist_without_compilation_marker","album",key,field="artist",album=key))
        self.reconcile(db,findings,scope=("album",key),job_id=job_id); return findings

    def analyze_artist_rows(self, db, key, rows, job_id=None):
        findings=[]; spellings={s.artist for s in rows if s.artist}
        normalized={normalize(x,artist=True) for x in spellings}
        if len(spellings)>1 and len(normalized)==1:
            findings.append(self._finding("artist_name_variants","artist",key,field="artist",artist=key,evidence={"variants":min(len(spellings),20)}))
            if len({x.casefold() for x in spellings})==1: findings.append(self._finding("inconsistent_artist_capitalization","artist",key,field="artist",artist=key))
        if any(x != x.strip() or re.search(r"\s{2,}",x) for x in spellings): findings.append(self._finding("suspicious_artist_spacing","artist",key,field="artist",artist=key))
        # The current schema has recording IDs only; do not guess an artist ID.
        self.reconcile(db,findings,scope=("artist",key),job_id=job_id); return findings

    def analyze_album(self, db, key, job_id=None):
        rows=list(db.scalars(select(Song).where(Song.availability_status=="available")).all())
        selected=[s for s in rows if self.album_key(s)==key]
        if not selected: raise LookupError("Album not found")
        return self.analyze_album_rows(db,key,selected,job_id)
    def analyze_artist(self, db, key, job_id=None):
        rows=list(db.scalars(select(Song).where(Song.availability_status=="available")).all())
        selected=[s for s in rows if self.artist_key(s.artist)==key]
        if not selected: raise LookupError("Artist not found")
        return self.analyze_artist_rows(db,key,selected,job_id)
    def list(self, db, **filters):
        limit=filters.pop("limit",50); offset=filters.pop("offset",0); q=select(MetadataIssue); clauses=[]
        ranges={"first_detected_from":("first_detected_at",">="),"first_detected_to":("first_detected_at","<="),"last_detected_from":("last_detected_at",">="),"last_detected_to":("last_detected_at","<="),"resolved_from":("resolved_at",">="),"resolved_to":("resolved_at","<="),"ignored_from":("ignored_at",">="),"ignored_to":("ignored_at","<=")}
        for key,value in filters.items():
            if key in ranges and value is not None:
                column, op=ranges[key]; clauses.append(getattr(MetadataIssue,column) >= value if op==">=" else getattr(MetadataIssue,column) <= value); continue
            if value is not None and hasattr(MetadataIssue,key): clauses.append(getattr(MetadataIssue,key)==value)
        q=q.where(*clauses); total=db.scalar(select(func.count()).select_from(q.subquery())) or 0
        return list(db.scalars(q.order_by(MetadataIssue.last_detected_at.desc(),MetadataIssue.id.desc()).offset(offset).limit(limit))), total
    def score(self, db):
        weights={"info":1,"warning":3,"error":8,"critical":15}; rows=list(db.scalars(select(MetadataIssue).where(MetadataIssue.status=="open")).all())
        # Cap each album/entity contribution so one release cannot dominate.
        grouped=Counter();
        for x in rows: grouped[(x.entity_type,x.album_key or x.entity_id)] += weights[x.severity]
        penalty=sum(min(value,25) for value in grouped.values()); available=db.scalar(select(func.count()).select_from(Song).where(Song.availability_status=="available")) or 0
        return {"score":max(0,100-round(100*penalty/max(available*10,1))),"inputs":{"available_songs":available,"open_issues":len(rows),"penalty":penalty,"weights":weights,"per_entity_cap":25},"diagnostic_only":True}
    def resolve_verified(self, db, issue_id):
        issue=db.get(MetadataIssue,issue_id)
        if not issue: raise LookupError("Metadata issue not found")
        issue.status="resolved"; issue.resolved_at=utcnow_naive(); return issue

metadata_health=MetadataHealthService()
def serialize_issue(x):
    return {k:getattr(x,k) for k in ("id","rule_id","rule_version","entity_type","entity_id","song_id","album_key","artist_key","field_name","severity","status","title","explanation","current_value","normalized_value","suggested_action","automatically_repairable","first_detected_at","last_detected_at","resolved_at","ignored_at","detection_job_id")} | {"evidence":json.loads(x.evidence or "{}")}

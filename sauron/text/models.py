"""Text ingestion models — source-agnostic normalized types.

After normalization by a source adapter (e.g., IMessageAdapter), the rest of
Sauron only deals with these objects. No Apple-specific assumptions about
threads, participants, reactions, or metadata should leak past the adapter
boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


# ═══════════════════════════════════════════════════════════════
# Source-Agnostic Normalized Text Event
# ═══════════════════════════════════════════════════════════════

@dataclass
class TextEvent:
    """A single normalized text message from any source.

    Produced by source adapters (IMessageAdapter, future Signal/WhatsApp).
    Consumed by ingest, clustering, and extraction stages — none of which
    should need to know which platform the message came from.
    """
    # Source identification
    source: str                        # 'imessage', 'signal', 'whatsapp', 'manual'
    source_message_id: str             # platform-specific unique ID (chat.db ROWID)
    thread_identifier: str             # platform-specific thread/chat ID
    thread_type: str                   # '1on1' or 'group'

    # Participant
    sender_phone: str | None           # E.164 normalized (None for sent messages from self)
    sender_name: str | None            # display name if available from source
    direction: str                     # 'sent' or 'received'

    # Content
    content: str | None                # message text (None for attachment-only)
    content_type: str                  # 'text', 'attachment', 'link', 'reaction', 'edit', 'unsend'
    timestamp: datetime

    # Thread context
    is_group: bool
    group_name: str | None             # display name for group chats
    participant_phones: list[str]      # all participants in thread (E.164)

    # Attachment / link metadata (preserved even if not analyzed in Phase 1)
    attachment_type: str | None = None     # 'image', 'pdf', 'url', 'audio', 'video', etc.
    attachment_filename: str | None = None
    attachment_url: str | None = None      # extracted URL if content_type='link'

    # Reaction / edit tracking
    refers_to_message_id: str | None = None  # for reactions/edits: source ID of referenced msg
    is_from_me: bool = False                 # preserved from chat.db for identity resolution

    # Platform-specific extras (anything that doesn't fit above)
    raw_metadata: dict | None = None


# ═══════════════════════════════════════════════════════════════
# Clustering Configuration
# ═══════════════════════════════════════════════════════════════

@dataclass
class ClusterConfig:
    """Configuration for the overnight-split clustering algorithm.

    Defaults are tuned for typical iMessage patterns. Group chats use
    wider thresholds (group_hard_split_hours) because multi-party
    conversations are harder to segment correctly.
    """
    day_boundary_hour: int = 5         # 5 AM local = overnight split point
    hard_split_hours: float = 8.0      # force split even intraday if gap exceeds this
    group_hard_split_hours: float = 12.0  # more conservative for group chats
    max_cluster_messages: int = 200    # safety cap; split if exceeded


# ═══════════════════════════════════════════════════════════════
# Message Cluster (output of clustering stage)
# ═══════════════════════════════════════════════════════════════

@dataclass
class MessageCluster:
    """A conversation cluster — the unit of extraction and review.

    Contains an ordered list of message IDs (exact provenance) plus
    summary stats used by the triage stage to assign a depth lane.
    """
    cluster_id: str                        # generated UUID
    thread_identifier: str                 # which thread this cluster belongs to
    thread_type: str                       # '1on1' or 'group'
    message_ids: list[str]                 # ordered list of TextEvent.source_message_id
    start_time: datetime
    end_time: datetime
    message_count: int
    total_chars: int                       # sum of content lengths (for triage input)
    participant_phones: list[str]          # unique participants in this cluster
    participant_count: int

    # Assigned by triage (None until triage runs)
    depth_lane: int | None = None          # 0/1/2/3
    cluster_method: str = "overnight_split"  # 'overnight_split', 'manual_split', 'manual_merge'

    # Merge/split provenance
    merged_from: list[str] = field(default_factory=list)   # cluster IDs if created by merge
    split_from: str | None = None                          # cluster ID if created by split

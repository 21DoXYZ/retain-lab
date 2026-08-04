"use client";

import { useState } from "react";
import { Collapsible, Button, Badge, Textarea, EmptyState } from "@/components/ui";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format";
import type { UserRole } from "@/lib/types";
import {
  NOTE_TAGS,
  TAG_LABELS,
  TAG_TONE,
  type NoteTag,
  canDeleteNote,
  isWithinEditWindow,
} from "./access";
import { addNote, updateNote, deleteNote, cardErrorText } from "./data";
import type { NoteRow } from "./types";

/**
 * Notes block (ТЗ п.4). Full transparency: every note the caller may see (RLS)
 * is listed with its author's name and time. Structured tag chips are model
 * feedback; the "оффер не подошёл" (offer_declined) tag binds to the currently
 * active offer (summary.recommendation). Authors may edit their own note for 15
 * minutes (UI + re-check on save); only head_retention/super_admin may delete.
 */
interface NotesBlockProps {
  playerId: number;
  meId: string;
  meRole: UserRole;
  canWrite: boolean;
  /** Active offer to bind to the offer_declined tag (from summary). */
  currentOffer: string | null;
  notes: NoteRow[];
  names: Map<string, string>;
  onChanged: () => void;
  /** true → только тело (для объединённого блока OpsJournal, без Collapsible). */
  embedded?: boolean;
}

function nameOf(
  id: string,
  meId: string,
  names: Map<string, string>,
  t: ReturnType<typeof useT>,
): string {
  if (id === meId) return t("card.common.you");
  return names.get(id) ?? t("card.common.operatorFallback", { id: id.slice(-4) });
}

export function NotesBlock({
  playerId,
  meId,
  meRole,
  canWrite,
  currentOffer,
  notes,
  names,
  onChanged,
  embedded = false,
}: NotesBlockProps) {
  const t = useT();
  const [content, setContent] = useState("");
  const [tags, setTags] = useState<NoteTag[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // inline edit
  const [editId, setEditId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");
  const [editTags, setEditTags] = useState<NoteTag[]>([]);

  const canDelete = canDeleteNote(meRole);

  function toggle(list: NoteTag[], tag: NoteTag): NoteTag[] {
    return list.includes(tag) ? list.filter((x) => x !== tag) : [...list, tag];
  }

  function linkedOfferFor(selected: NoteTag[]): string | null {
    return selected.includes("offer_declined") ? currentOffer : null;
  }

  async function submit() {
    if (!content.trim()) {
      setError(t("card.notes.emptyContent"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await addNote({
        playerId,
        authorId: meId,
        content: content.trim(),
        tags,
        linkedOffer: linkedOfferFor(tags),
      });
      setContent("");
      setTags([]);
      onChanged();
    } catch (e) {
      setError(cardErrorText(e, t, "card.common.error"));
    } finally {
      setBusy(false);
    }
  }

  function startEdit(note: NoteRow) {
    setEditId(note.id);
    setEditContent(note.content);
    setEditTags(note.tags.filter((tag): tag is NoteTag => (NOTE_TAGS as readonly string[]).includes(tag)));
    setError(null);
  }

  async function saveEdit(note: NoteRow) {
    if (!isWithinEditWindow(note.created_at)) {
      setError(t("card.notes.editWindowExpired"));
      setEditId(null);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await updateNote({
        id: note.id,
        authorId: meId,
        playerId,
        content: editContent.trim(),
        tags: editTags,
        linkedOffer: linkedOfferFor(editTags),
      });
      setEditId(null);
      onChanged();
    } catch (e) {
      setError(cardErrorText(e, t, "card.common.error"));
    } finally {
      setBusy(false);
    }
  }

  async function remove(note: NoteRow) {
    setBusy(true);
    setError(null);
    try {
      await deleteNote({ id: note.id, actorId: meId, playerId });
      onChanged();
    } catch (e) {
      setError(cardErrorText(e, t, "card.common.error"));
    } finally {
      setBusy(false);
    }
  }

  const body = (
    <>
      {/* Add note */}
      {canWrite ? (
        <div className="mt-3">
          <Textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder={t("card.notes.placeholder")}
          />
          <TagChips
            selected={tags}
            onToggle={(tag) => setTags((prev) => toggle(prev, tag))}
            currentOffer={currentOffer}
          />
          <div className="mt-2 flex items-center justify-between gap-3">
            {error ? <span className="text-[12.5px] text-neg">{error}</span> : <span />}
            <Button variant="brand" size="sm" onClick={submit} loading={busy}>
              {t("card.notes.addButton")}
            </Button>
          </div>
        </div>
      ) : error ? (
        <div className="mt-3 text-[12.5px] text-neg">{error}</div>
      ) : null}

      {/* List */}
      <div className="mt-4">
        {notes.length === 0 ? (
          <EmptyState
            icon="🗒"
            title={t("card.notes.emptyTitle")}
            description={canWrite ? t("card.notes.emptyDescription") : undefined}
            className="py-8"
          />
        ) : (
          <ul className="flex flex-col divide-y divide-hair">
            {notes.map((note) => {
              const mine = note.author_id === meId;
              const editable = mine && isWithinEditWindow(note.created_at);
              const isEditing = editId === note.id;
              return (
                <li key={note.id} className="py-3">
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <div className="text-[12.5px]">
                      <b className="text-slate">{nameOf(note.author_id, meId, names, t)}</b>{" "}
                      <span className="text-steel">· {formatDateTime(note.created_at)}</span>
                      {note.updated_at !== note.created_at ? (
                        <span className="text-stone">{t("card.notes.editedSuffix")}</span>
                      ) : null}
                    </div>
                    <div className="flex gap-1.5">
                      {editable && !isEditing ? (
                        <Button size="sm" variant="ghost" onClick={() => startEdit(note)} disabled={busy}>
                          {t("card.notes.editButton")}
                        </Button>
                      ) : null}
                      {canDelete ? (
                        <Button size="sm" variant="ghost" onClick={() => remove(note)} disabled={busy}>
                          {t("card.notes.deleteButton")}
                        </Button>
                      ) : null}
                    </div>
                  </div>

                  {isEditing ? (
                    <div className="mt-2">
                      <Textarea
                        value={editContent}
                        onChange={(e) => setEditContent(e.target.value)}
                      />
                      <TagChips
                        selected={editTags}
                        onToggle={(tag) => setEditTags((prev) => toggle(prev, tag))}
                        currentOffer={currentOffer}
                      />
                      <div className="mt-2 flex gap-2 justify-end">
                        <Button size="sm" variant="ghost" onClick={() => setEditId(null)}>
                          {t("ui.cancel")}
                        </Button>
                        <Button size="sm" variant="brand" onClick={() => saveEdit(note)} loading={busy}>
                          {t("ui.save")}
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div className="mt-1 text-[13.5px] text-ink whitespace-pre-wrap">
                        {note.content}
                      </div>
                      {note.tags.length > 0 ? (
                        <div className="mt-1.5 flex gap-1.5 flex-wrap items-center">
                          {note.tags.map((tag) => {
                            const tone = TAG_TONE[tag as NoteTag];
                            const labelKey = TAG_LABELS[tag as NoteTag];
                            return (
                              <Badge key={tag} bg={tone?.bg ?? "#eff6ff"} fg={tone?.fg ?? "#1d4ed8"}>
                                {labelKey ? t(labelKey) : tag}
                              </Badge>
                            );
                          })}
                          {note.linked_offer ? (
                            <span className="text-[12px] text-steel">
                              {t("card.notes.linkedOfferPrefix")}{" "}
                              <b className="text-slate">{note.linked_offer}</b>
                            </span>
                          ) : null}
                        </div>
                      ) : null}
                    </>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </>
  );
  if (embedded) return body;
  return (
    <Collapsible
      title={t("card.notes.title")}
      count={notes.length}
      hint={t("card.notes.hint")}
      defaultOpen={notes.length > 0}
    >
      {body}
    </Collapsible>
  );
}

function TagChips({
  selected,
  onToggle,
  currentOffer,
}: {
  selected: NoteTag[];
  onToggle: (tag: NoteTag) => void;
  currentOffer: string | null;
}) {
  const t = useT();
  return (
    <div className="mt-2 flex gap-1.5 flex-wrap items-center">
      {NOTE_TAGS.map((tag) => {
        const on = selected.includes(tag);
        return (
          <button
            key={tag}
            type="button"
            onClick={() => onToggle(tag)}
            className={cn(
              "text-[12px] rounded-full px-2.5 py-1 border transition-colors cursor-pointer",
              on
                ? "bg-ink text-white border-ink"
                : "bg-canvas text-steel border-hair2 hover:border-primary hover:text-primary",
            )}
          >
            {t(TAG_LABELS[tag])}
          </button>
        );
      })}
      {selected.includes("offer_declined") ? (
        <span className="text-[12px] text-steel">
          {currentOffer ? (
            <>
              {t("card.notes.tagLinkedOfferPrefix")} <b className="text-slate">{currentOffer}</b>
            </>
          ) : (
            t("card.notes.noActiveOffer")
          )}
        </span>
      ) : null}
    </div>
  );
}

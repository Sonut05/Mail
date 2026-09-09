import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  Users, Search, Star, Mail, ArrowUpRight, Clock, AlertCircle, 
  MessageSquare, ChevronRight, X, Sparkles, Filter
} from 'lucide-react';
import { fetchContactsList, fetchContactDetail, recordFeedbackSignal } from '../services/api';

export default function Contacts() {
  const navigate = useNavigate();
  const [contacts, setContacts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState('importance');
  const [selectedContact, setSelectedContact] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [hasNext, setHasNext] = useState(false);
  const [total, setTotal] = useState(0);

  const loadContacts = (q = searchQuery, sort = sortBy, p = 1) => {
    setLoading(true);
    fetchContactsList({ q, sort, page: p, per_page: 24 })
      .then((res) => {
        if (res && res.contacts) {
          setContacts(res.contacts);
          setTotal(res.total || 0);
          setHasNext(res.has_next || false);
        }
      })
      .catch((err) => console.error('Failed to load contacts:', err))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadContacts(searchQuery, sortBy, page);
  }, [sortBy, page]);

  const handleSearchSubmit = (e) => {
    e.preventDefault();
    setPage(1);
    loadContacts(searchQuery, sortBy, 1);
  };

  const handleSelectContact = (contact) => {
    setSelectedContact(contact);
    setDetailLoading(true);
    fetchContactDetail(contact.email)
      .then((res) => {
        if (res && res.contact) {
          setSelectedContact(res.contact);
        }
      })
      .catch((err) => console.error('Error fetching contact detail:', err))
      .finally(() => setDetailLoading(false));
  };

  const handleToggleImportant = async (contact, e) => {
    e.stopPropagation();
    const newWeight = contact.is_important ? -2.0 : 2.0;
    const sigType = contact.is_important ? 'mark_unimportant' : 'mark_important';

    try {
      await recordFeedbackSignal(sigType, 'sender', contact.email, newWeight);
      setContacts((prev) =>
        prev.map((c) =>
          c.email === contact.email
            ? { ...c, is_important: !c.is_important, importance_score: Math.min(100, Math.max(10, c.importance_score + (newWeight > 0 ? 15 : -15))) }
            : c
        )
      );
      if (selectedContact?.email === contact.email) {
        setSelectedContact((prev) => ({
          ...prev,
          is_important: !prev.is_important,
        }));
      }
    } catch (err) {
      console.error('Failed to record signal:', err);
    }
  };

  const handleFilterInbox = (emailAddress) => {
    navigate(`/inbox?sender=${encodeURIComponent(emailAddress)}`);
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2.5">
            <Users className="text-indigo-400" size={26} />
            Contact & People Intelligence
          </h1>
          <p className="text-sm text-white/60">
            Observable engagement, priority contacts, open action items, and topic history.
          </p>
        </div>

        {/* Search & Sort Controls */}
        <div className="flex items-center gap-3 flex-wrap">
          <form onSubmit={handleSearchSubmit} className="relative min-w-[240px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-white/40" size={16} />
            <input
              type="text"
              placeholder="Search by name or email..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-4 py-2 rounded-xl bg-white/5 border border-white/10 text-white placeholder-white/40 text-sm focus:outline-none focus:border-indigo-500/50 transition-colors"
            />
          </form>

          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            className="px-3.5 py-2 rounded-xl bg-white/5 border border-white/10 text-white text-sm focus:outline-none focus:border-indigo-500/50 transition-colors cursor-pointer"
          >
            <option value="importance" className="bg-[#181b26]">Sort by Importance</option>
            <option value="activity" className="bg-[#181b26]">Sort by Recent Activity</option>
            <option value="volume" className="bg-[#181b26]">Sort by Message Volume</option>
            <option value="alphabetical" className="bg-[#181b26]">Sort Alphabetically</option>
          </select>
        </div>
      </div>

      {/* Stats summary bar */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div className="glass-card p-4 rounded-xl border border-white/5 bg-white/[0.02]">
          <div className="text-xs text-white/50 font-medium">Total Contacts</div>
          <div className="text-2xl font-bold text-white mt-1">{total}</div>
        </div>
        <div className="glass-card p-4 rounded-xl border border-white/5 bg-white/[0.02]">
          <div className="text-xs text-indigo-400 font-medium">High Importance</div>
          <div className="text-2xl font-bold text-white mt-1">
            {contacts.filter((c) => c.importance_score >= 70).length}
          </div>
        </div>
        <div className="glass-card p-4 rounded-xl border border-white/5 bg-white/[0.02]">
          <div className="text-xs text-rose-400 font-medium">Pending Actions</div>
          <div className="text-2xl font-bold text-white mt-1">
            {contacts.filter((c) => c.open_actions_count > 0).length}
          </div>
        </div>
        <div className="glass-card p-4 rounded-xl border border-white/5 bg-white/[0.02]">
          <div className="text-xs text-amber-400 font-medium">Waiting Threads</div>
          <div className="text-2xl font-bold text-white mt-1">
            {contacts.filter((c) => c.waiting_threads_count > 0).length}
          </div>
        </div>
      </div>

      {/* Grid of Contacts */}
      {loading ? (
        <div className="py-24 text-center text-white/40 animate-pulse">
          Loading contact intelligence...
        </div>
      ) : contacts.length === 0 ? (
        <div className="glass-card p-12 text-center rounded-2xl border border-white/5">
          <Users className="mx-auto text-white/20 mb-3" size={40} />
          <h3 className="text-base font-semibold text-white">No contacts found</h3>
          <p className="text-sm text-white/50 mt-1">
            {searchQuery ? 'Try adjusting your search query.' : 'Contacts will appear once emails are synced.'}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {contacts.map((contact) => (
            <div
              key={contact.email}
              onClick={() => handleSelectContact(contact)}
              className="glass-card p-5 rounded-2xl border border-white/5 bg-white/[0.02] hover:bg-white/[0.05] hover:border-indigo-500/30 transition-all duration-200 cursor-pointer flex flex-col justify-between group"
            >
              <div>
                {/* Top row: Avatar & Importance badge */}
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-white font-bold text-sm uppercase shadow-sm shrink-0">
                      {contact.name[0] || contact.email[0]}
                    </div>
                    <div className="min-w-0">
                      <div className="font-semibold text-white truncate text-base group-hover:text-indigo-300 transition-colors">
                        {contact.name}
                      </div>
                      <div className="text-xs text-white/50 truncate font-mono">
                        {contact.email}
                      </div>
                    </div>
                  </div>

                  <button
                    onClick={(e) => handleToggleImportant(contact, e)}
                    className={`p-1.5 rounded-lg transition-colors ${
                      contact.is_important
                        ? 'text-amber-400 bg-amber-400/10 hover:bg-amber-400/20'
                        : 'text-white/20 hover:text-white/60 hover:bg-white/5'
                    }`}
                    title={contact.is_important ? 'Important Contact' : 'Mark as Important'}
                  >
                    <Star size={16} fill={contact.is_important ? 'currentColor' : 'none'} />
                  </button>
                </div>

                {/* Score & Badges */}
                <div className="flex items-center gap-2 mt-4 flex-wrap">
                  <span
                    className={`text-xs px-2.5 py-0.5 rounded-full font-semibold border ${
                      contact.importance_score >= 80
                        ? 'bg-rose-500/15 text-rose-300 border-rose-500/30'
                        : contact.importance_score >= 60
                        ? 'bg-amber-500/15 text-amber-300 border-amber-500/30'
                        : 'bg-indigo-500/15 text-indigo-300 border-indigo-500/30'
                    }`}
                  >
                    Score: {contact.importance_score}
                  </span>

                  {contact.open_actions_count > 0 && (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-rose-500/10 text-rose-300 border border-rose-500/20 flex items-center gap-1 font-medium">
                      <AlertCircle size={11} /> {contact.open_actions_count} Action{contact.open_actions_count > 1 ? 's' : ''}
                    </span>
                  )}

                  {contact.waiting_threads_count > 0 && (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-300 border border-amber-500/20 flex items-center gap-1 font-medium">
                      <Clock size={11} /> {contact.waiting_threads_count} Waiting
                    </span>
                  )}
                </div>

                {/* Topics */}
                {contact.recent_topics && contact.recent_topics.length > 0 && (
                  <div className="flex items-center gap-1.5 mt-3 flex-wrap">
                    {contact.recent_topics.map((top, idx) => (
                      <span key={idx} className="text-[11px] px-2 py-0.5 rounded bg-white/5 text-white/60 border border-white/5">
                        #{top}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* Bottom footer */}
              <div className="mt-4 pt-3 border-t border-white/5 flex items-center justify-between text-xs text-white/50">
                <span>{contact.message_count} messages</span>
                <span className="flex items-center gap-1 group-hover:text-indigo-300 transition-colors">
                  View Intelligence <ChevronRight size={13} />
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Pagination */}
      {total > 24 && (
        <div className="flex items-center justify-center gap-3 pt-4">
          <button
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            className="px-4 py-2 rounded-xl bg-white/5 hover:bg-white/10 text-sm font-medium text-white disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            Previous
          </button>
          <span className="text-xs text-white/50">
            Page {page} of {Math.ceil(total / 24)}
          </span>
          <button
            disabled={!hasNext}
            onClick={() => setPage((p) => p + 1)}
            className="px-4 py-2 rounded-xl bg-white/5 hover:bg-white/10 text-sm font-medium text-white disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            Next
          </button>
        </div>
      )}

      {/* Contact Detail Modal / Drawer */}
      {selectedContact && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 overflow-y-auto">
          <div className="relative w-full max-w-2xl bg-[#131620]/95 border border-white/10 rounded-2xl shadow-2xl p-6 text-white max-h-[90vh] flex flex-col">
            <div className="flex items-start justify-between pb-4 border-b border-white/10">
              <div className="flex items-center gap-3">
                <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-white font-bold text-lg uppercase shadow-md">
                  {selectedContact.name[0] || selectedContact.email[0]}
                </div>
                <div>
                  <h2 className="text-xl font-bold text-white flex items-center gap-2">
                    {selectedContact.name}
                    {selectedContact.is_important && (
                      <Star size={16} className="text-amber-400 fill-current" />
                    )}
                  </h2>
                  <p className="text-xs text-white/60 font-mono">{selectedContact.email}</p>
                </div>
              </div>
              <button
                onClick={() => setSelectedContact(null)}
                className="p-2 rounded-xl bg-white/5 hover:bg-white/10 text-white/70 hover:text-white transition-colors"
              >
                <X size={20} />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto space-y-4 py-4 pr-1">
              {/* Stat Grid */}
              <div className="grid grid-cols-3 gap-3">
                <div className="p-3 bg-white/5 rounded-xl border border-white/5 text-center">
                  <div className="text-xs text-white/50">Total Emails</div>
                  <div className="text-lg font-bold text-white mt-0.5">{selectedContact.message_count}</div>
                </div>
                <div className="p-3 bg-white/5 rounded-xl border border-white/5 text-center">
                  <div className="text-xs text-white/50">Importance</div>
                  <div className="text-lg font-bold text-indigo-400 mt-0.5">{selectedContact.importance_score} / 100</div>
                </div>
                <div className="p-3 bg-white/5 rounded-xl border border-white/5 text-center">
                  <div className="text-xs text-white/50">Open Actions</div>
                  <div className="text-lg font-bold text-rose-400 mt-0.5">{selectedContact.open_actions_count}</div>
                </div>
              </div>

              {/* Topics */}
              {selectedContact.recent_topics && selectedContact.recent_topics.length > 0 && (
                <div className="p-4 bg-white/5 rounded-xl border border-white/5">
                  <div className="text-xs font-semibold text-white/70 uppercase tracking-wider mb-2">
                    Recent Topics Discussed
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {selectedContact.recent_topics.map((t, idx) => (
                      <span key={idx} className="text-xs px-2.5 py-1 rounded-md bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 font-medium">
                        #{t}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Recent interactions */}
              <div className="space-y-2">
                <div className="text-xs font-semibold text-white/70 uppercase tracking-wider">
                  Recent Interactions
                </div>
                {detailLoading ? (
                  <div className="py-6 text-center text-xs text-white/40 animate-pulse">
                    Loading recent emails...
                  </div>
                ) : selectedContact.recent_emails && selectedContact.recent_emails.length > 0 ? (
                  <div className="space-y-2">
                    {selectedContact.recent_emails.map((em) => (
                      <div
                        key={em.id}
                        className="p-3 rounded-xl bg-white/[0.03] border border-white/5 hover:border-white/10 transition-colors text-xs space-y-1"
                      >
                        <div className="flex items-center justify-between font-medium text-white">
                          <span className="truncate pr-2">{em.subject || '(No Subject)'}</span>
                          <span className="text-white/40 text-[11px] shrink-0">
                            {em.received_at ? new Date(em.received_at).toLocaleDateString() : ''}
                          </span>
                        </div>
                        {em.ai_summary && (
                          <p className="text-white/60 line-clamp-2 text-[11px]">
                            {em.ai_summary}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-xs text-white/40 italic p-3">
                    No recent interaction history available.
                  </div>
                )}
              </div>
            </div>

            {/* Modal Actions */}
            <div className="pt-4 border-t border-white/10 flex items-center justify-between gap-3">
              <button
                onClick={() => handleFilterInbox(selectedContact.email)}
                className="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-xs font-medium text-white flex items-center gap-1.5 transition-colors shadow-sm"
              >
                <Mail size={14} /> Filter All Emails in Inbox
              </button>

              <button
                onClick={() => setSelectedContact(null)}
                className="px-4 py-2 rounded-xl bg-white/10 hover:bg-white/15 text-xs font-medium text-white transition-colors"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

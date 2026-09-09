import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  MapPin,
  User,
  ExternalLink,
  Bell,
  CheckCircle2,
  CalendarDays,
  Plus,
  Link2,
  Trash2,
  Edit3,
  X,
  AlertTriangle,
  AlertCircle,
  Clock,
} from 'lucide-react';
import { useApp } from '../context/AppContext';

function groupByDate(events) {
  const groups = {};
  events.forEach((event) => {
    const dateKey = event.date || (event.start_date_time ? event.start_date_time.split('T')[0] : 'No Date');
    if (!groups[dateKey]) groups[dateKey] = [];
    groups[dateKey].push(event);
  });
  return Object.entries(groups).sort(([a], [b]) => a.localeCompare(b));
}

function formatDate(dateStr) {
  if (!dateStr || dateStr === 'No Date') return 'Unscheduled';
  const date = new Date(dateStr + 'T00:00:00');
  if (isNaN(date.getTime())) return dateStr;

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const tomorrow = new Date(today);
  tomorrow.setDate(tomorrow.getDate() + 1);

  if (date.getTime() === today.getTime()) return 'Today';
  if (date.getTime() === tomorrow.getTime()) return 'Tomorrow';

  return date.toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  });
}

export default function CalendarView() {
  const {
    calendarEvents,
    createCalendarEvent,
    updateCalendarEvent,
    deleteCalendarEvent,
  } = useApp();
  const navigate = useNavigate();

  const [activeReminders, setActiveReminders] = useState({});
  const [toastMessage, setToastMessage] = useState(null);

  // Modal State
  const [modalOpen, setModalOpen] = useState(false);
  const [editingEvent, setEditingEvent] = useState(null);

  // Form Fields
  const [formTitle, setFormTitle] = useState('');
  const [formDesc, setFormDesc] = useState('');
  const [formDate, setFormDate] = useState('');
  const [formStartTime, setFormStartTime] = useState('10:00');
  const [formEndTime, setFormEndTime] = useState('11:00');
  const [formLocation, setFormLocation] = useState('');
  const [formLink, setFormLink] = useState('');
  const [formError, setFormError] = useState('');
  const [conflictWarning, setConflictWarning] = useState(null);
  const [saving, setSaving] = useState(false);

  // Initialize active reminders from calendar events
  useEffect(() => {
    const initial = {};
    (calendarEvents || []).forEach((e) => {
      if (e.hasReminder || e.priority === 'high') {
        initial[e.id] = true;
      }
    });
    setActiveReminders(initial);
  }, [calendarEvents]);

  const showToast = (msg) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 4000);
  };

  const openNewEventModal = () => {
    setEditingEvent(null);
    setFormTitle('');
    setFormDesc('');
    const today = new Date().toISOString().split('T')[0];
    setFormDate(today);
    setFormStartTime('10:00');
    setFormEndTime('11:00');
    setFormLocation('');
    setFormLink('');
    setFormError('');
    setConflictWarning(null);
    setModalOpen(true);
  };

  const openEditEventModal = (event) => {
    setEditingEvent(event);
    setFormTitle(event.title || '');
    setFormDesc(event.description || '');
    const d = event.date || (event.start_date_time ? event.start_date_time.split('T')[0] : '');
    setFormDate(d);

    if (event.start_date_time) {
      const s = new Date(event.start_date_time);
      setFormStartTime(s.toTimeString().slice(0, 5));
    } else {
      setFormStartTime('10:00');
    }

    if (event.end_date_time) {
      const e = new Date(event.end_date_time);
      setFormEndTime(e.toTimeString().slice(0, 5));
    } else {
      setFormEndTime('11:00');
    }

    setFormLocation(event.location || '');
    setFormLink(event.meeting_link || event.meetingLink || '');
    setFormError('');
    setConflictWarning(null);
    setModalOpen(true);
  };

  const handleFormSubmit = async (e) => {
    e.preventDefault();
    if (!formTitle.trim()) {
      setFormError('Event title is required.');
      return;
    }
    if (!formDate || !formStartTime || !formEndTime) {
      setFormError('Date, start time, and end time are required.');
      return;
    }

    const startIso = `${formDate}T${formStartTime}:00`;
    const endIso = `${formDate}T${formEndTime}:00`;

    if (new Date(endIso) <= new Date(startIso)) {
      setFormError('Event end time must be after start time.');
      return;
    }

    setSaving(true);
    setFormError('');

    try {
      if (editingEvent) {
        const res = await updateCalendarEvent(editingEvent.id, {
          title: formTitle.trim(),
          description: formDesc.trim(),
          start: startIso,
          end: endIso,
          location: formLocation.trim(),
          meeting_link: formLink.trim(),
        });
        if (res && res.has_conflict && res.conflicts?.length > 0) {
          showToast(`⚠️ Schedule conflict detected with "${res.conflicts[0].title}". Event updated.`);
        } else {
          showToast('Event updated successfully.');
        }
      } else {
        const res = await createCalendarEvent({
          title: formTitle.trim(),
          description: formDesc.trim(),
          start: startIso,
          end: endIso,
          location: formLocation.trim(),
          meeting_link: formLink.trim(),
        });
        if (!res.success) {
          throw new Error(res.error || 'Failed to create event.');
        }
        if (res.has_conflict && res.conflicts?.length > 0) {
          showToast(`⚠️ Schedule conflict detected with "${res.conflicts[0].title}". Event created.`);
        } else {
          showToast('Event created successfully.');
        }
      }
      setModalOpen(false);
    } catch (err) {
      setFormError(err.message || 'Failed to save calendar event.');
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteEvent = async (eventId) => {
    if (window.confirm('Are you sure you want to delete this calendar event?')) {
      try {
        await deleteCalendarEvent(eventId);
        showToast('Calendar event deleted.');
      } catch (err) {
        console.error('Failed to delete event:', err);
      }
    }
  };

  const handleToggleReminder = (event) => {
    const isCurrentlySet = !!activeReminders[event.id];
    const newStatus = !isCurrentlySet;

    setActiveReminders((prev) => ({
      ...prev,
      [event.id]: newStatus,
    }));

    if (newStatus) {
      if ('Notification' in window) {
        if (Notification.permission === 'default') {
          Notification.requestPermission();
        }
        if (Notification.permission === 'granted') {
          new Notification('🔔 MailMind AI — Reminder Active', {
            body: `Notification set for: "${event.title}" on ${formatDate(event.date)} at ${event.time}`,
            icon: '/vite.svg',
          });
        }
      }
      showToast(`🔔 Reminder Set for "${event.title}"`);
    } else {
      showToast(`🔕 Reminder disabled for "${event.title}"`);
    }
  };

  const grouped = groupByDate(calendarEvents);

  const renderTimeline = () => {
    if (calendarEvents.length === 0) {
      return (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '80px 24px',
          background: 'var(--bg-glass)',
          backdropFilter: 'blur(12px)',
          borderRadius: '16px',
          border: '1px solid var(--border-glass)',
          textAlign: 'center',
          marginTop: '24px',
        }}>
          <CalendarDays size={48} style={{ color: 'var(--color-indigo)', marginBottom: '16px', opacity: 0.8 }} />
          <h3 style={{ fontSize: '1.15rem', fontWeight: '600', color: 'var(--text-primary)', marginBottom: '8px' }}>
            Your Schedule is Clear
          </h3>
          <p style={{ color: 'var(--text-secondary)', maxWidth: '420px', fontSize: '0.875rem', lineHeight: '1.5', marginBottom: '16px' }}>
            Create manual meetings or confirm AI-suggested events from your synchronized emails.
          </p>
          <button className="btn btn-primary" onClick={openNewEventModal}>
            <Plus size={16} /> New Event
          </button>
        </div>
      );
    }

    return grouped.map(([date, events]) => (
      <div key={date} className="calendar-date-group">
        <div className="calendar-date-label" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <CalendarDays size={16} style={{ color: 'var(--color-indigo)' }} />
          <span>{formatDate(date)}</span>
        </div>
        {events.map((event, i) => {
          const isDeadline = event.title?.toLowerCase().includes('last date') || event.title?.toLowerCase().includes('deadline');
          const isInterview = event.title?.toLowerCase().includes('interview');
          const hasReminderSet = !!activeReminders[event.id];

          return (
            <div
              key={event.id}
              className={`calendar-event-card animate-fadeIn stagger-${Math.min(i + 1, 5)}`}
              style={{
                borderLeft: isDeadline
                  ? '4px solid var(--color-danger, #EF4444)'
                  : isInterview
                  ? '4px solid var(--color-purple, #A855F7)'
                  : '4px solid var(--color-indigo, #6366F1)',
              }}
            >
              <div className="event-time-block">
                <span className="event-time">{event.time ? event.time.split(' ')[0] : '10:00'}</span>
                <span className="event-ampm">{event.time ? event.time.split(' ')[1] : 'AM'}</span>
                <span className="event-duration">{event.duration || '60m'}</span>
              </div>

              <div className={`event-divider ${isDeadline ? 'danger' : isInterview ? 'purple' : 'indigo'}`} />

              <div className="event-details" style={{ flexGrow: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px', flexWrap: 'wrap' }}>
                  {isDeadline ? (
                    <span style={{ fontSize: '0.6875rem', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.05em', padding: '2px 8px', borderRadius: '4px', background: 'rgba(239, 68, 68, 0.15)', color: '#EF4444', border: '1px solid rgba(239, 68, 68, 0.3)' }}>
                      🚨 Last Date / Deadline
                    </span>
                  ) : isInterview ? (
                    <span style={{ fontSize: '0.6875rem', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.05em', padding: '2px 8px', borderRadius: '4px', background: 'rgba(168, 85, 247, 0.15)', color: '#A855F7', border: '1px solid rgba(168, 85, 247, 0.3)' }}>
                      💼 Interview
                    </span>
                  ) : (
                    <span style={{ fontSize: '0.6875rem', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.05em', padding: '2px 8px', borderRadius: '4px', background: 'rgba(99, 102, 241, 0.15)', color: '#818CF8', border: '1px solid rgba(99, 102, 241, 0.3)' }}>
                      📅 Scheduled Event
                    </span>
                  )}

                  {event.email_id && (
                    <button
                      onClick={() => navigate('/inbox', { state: { selectEmailId: event.email_id } })}
                      style={{
                        background: 'rgba(99, 102, 241, 0.08)',
                        border: '1px solid rgba(99, 102, 241, 0.2)',
                        borderRadius: '4px',
                        padding: '1px 6px',
                        fontSize: '0.6875rem',
                        color: 'var(--color-indigo)',
                        cursor: 'pointer',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '3px',
                      }}
                      title="View Source Email"
                    >
                      <Link2 size={10} /> Source Email
                    </button>
                  )}
                </div>

                <div className="event-title" style={{ fontSize: '1rem', fontWeight: '600', color: 'var(--text-primary)', marginBottom: '4px' }}>
                  {event.title}
                </div>

                {event.description && (
                  <div style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', marginBottom: '8px', whiteSpace: 'pre-line' }}>
                    {event.description}
                  </div>
                )}

                <div className="event-meta">
                  <div className="event-meta-item">
                    <MapPin size={14} /> {event.location || 'Online'}
                  </div>
                  {event.organizer && (
                    <div className="event-meta-item">
                      <User size={14} /> {event.organizer}
                    </div>
                  )}
                  {event.meetingLink && (
                    <div className="event-meta-item" style={{ marginTop: '4px' }}>
                      <a
                        href={event.meetingLink}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '6px',
                          padding: '4px 10px',
                          borderRadius: '6px',
                          background: 'rgba(99, 102, 241, 0.15)',
                          color: '#818CF8',
                          border: '1px solid rgba(99, 102, 241, 0.3)',
                          fontSize: '0.75rem',
                          fontWeight: '600',
                          textDecoration: 'none',
                        }}
                      >
                        <ExternalLink size={12} />
                        Join Meeting Link
                      </a>
                    </div>
                  )}
                </div>
              </div>

              <div className="event-actions" style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                <button
                  type="button"
                  onClick={() => handleToggleReminder(event)}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px',
                    padding: '6px 12px',
                    borderRadius: '8px',
                    fontSize: '0.75rem',
                    fontWeight: '600',
                    cursor: 'pointer',
                    transition: 'all 0.2s ease',
                    background: hasReminderSet ? 'rgba(16, 185, 129, 0.15)' : 'rgba(255, 255, 255, 0.05)',
                    color: hasReminderSet ? '#10B981' : 'var(--text-secondary)',
                    border: hasReminderSet ? '1px solid rgba(16, 185, 129, 0.3)' : '1px solid var(--border-glass)',
                  }}
                  title={hasReminderSet ? 'Reminder is Active' : 'Click to set reminder'}
                >
                  {hasReminderSet ? (
                    <>
                      <CheckCircle2 size={13} />
                      <span>Reminder Set</span>
                    </>
                  ) : (
                    <>
                      <Bell size={13} />
                      <span>+ Set Reminder</span>
                    </>
                  )}
                </button>

                <button
                  type="button"
                  onClick={() => openEditEventModal(event)}
                  title="Edit Event"
                  style={{
                    background: 'none',
                    border: 'none',
                    color: 'var(--text-tertiary)',
                    cursor: 'pointer',
                    padding: '6px',
                  }}
                >
                  <Edit3 size={15} />
                </button>

                <button
                  type="button"
                  onClick={() => handleDeleteEvent(event.id)}
                  title="Delete Event"
                  style={{
                    background: 'none',
                    border: 'none',
                    color: 'var(--text-tertiary)',
                    cursor: 'pointer',
                    padding: '6px',
                  }}
                >
                  <Trash2 size={15} />
                </button>
              </div>
            </div>
          );
        })}
      </div>
    ));
  };

  return (
    <div className="calendar-page page-enter" style={{ position: 'relative' }}>
      {/* Toast Notification Banner */}
      {toastMessage && (
        <div
          style={{
            position: 'fixed',
            top: '24px',
            right: '24px',
            zIndex: 9999,
            background: 'rgba(18, 18, 24, 0.95)',
            backdropFilter: 'blur(16px)',
            border: '1px solid rgba(16, 185, 129, 0.4)',
            color: '#fff',
            padding: '12px 18px',
            borderRadius: '12px',
            boxShadow: '0 10px 30px rgba(0,0,0,0.5)',
            fontSize: '0.875rem',
            fontWeight: '500',
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            animation: 'fadeIn 0.3s ease',
          }}
        >
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Header with New Event Button */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <h2>
            <CalendarDays size={22} style={{ verticalAlign: 'middle', marginRight: '8px', color: 'var(--color-indigo)' }} />
            Calendar & Deadlines
          </h2>
          <p style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
            Scheduled events, interviews, and deadlines with automatic conflict detection
          </p>
        </div>
        <button className="btn btn-primary" onClick={openNewEventModal}>
          <Plus size={16} /> New Event
        </button>
      </div>

      <div className="calendar-timeline">
        {renderTimeline()}
      </div>

      {/* Manual Event Modal */}
      {modalOpen && (
        <div style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(0, 0, 0, 0.7)',
          backdropFilter: 'blur(6px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 9999,
          padding: '16px',
        }}>
          <div style={{
            background: '#13151f',
            border: '1px solid var(--glass-border)',
            borderRadius: 'var(--radius-lg)',
            width: '100%',
            maxWidth: '500px',
            padding: '24px',
            boxShadow: '0 20px 40px rgba(0, 0, 0, 0.6)',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h3 style={{ margin: 0, fontSize: '1.1rem', color: 'var(--text-primary)' }}>
                {editingEvent ? 'Edit Calendar Event' : 'Create Calendar Event'}
              </h3>
              <button
                onClick={() => setModalOpen(false)}
                style={{ background: 'none', border: 'none', color: 'var(--text-tertiary)', cursor: 'pointer' }}
              >
                <X size={18} />
              </button>
            </div>

            {formError && (
              <div style={{
                background: 'rgba(239, 68, 68, 0.1)',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                color: 'var(--color-danger)',
                padding: '8px 12px',
                borderRadius: '6px',
                fontSize: '0.8125rem',
                marginBottom: '16px',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
              }}>
                <AlertCircle size={14} /> {formError}
              </div>
            )}

            <form onSubmit={handleFormSubmit}>
              <div style={{ marginBottom: '14px' }}>
                <label style={{ display: 'block', fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: '6px', fontWeight: '500' }}>
                  Title <span style={{ color: 'var(--color-danger)' }}>*</span>
                </label>
                <input
                  type="text"
                  value={formTitle}
                  onChange={(e) => setFormTitle(e.target.value)}
                  placeholder="e.g. Technical Interview / Product Sync"
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    borderRadius: '6px',
                    background: 'rgba(255, 255, 255, 0.04)',
                    border: '1px solid var(--glass-border)',
                    color: 'var(--text-primary)',
                    fontSize: '0.875rem',
                    outline: 'none',
                  }}
                  required
                />
              </div>

              <div style={{ marginBottom: '14px' }}>
                <label style={{ display: 'block', fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: '6px', fontWeight: '500' }}>
                  Description
                </label>
                <textarea
                  value={formDesc}
                  onChange={(e) => setFormDesc(e.target.value)}
                  placeholder="Meeting agenda, preparation notes, etc."
                  rows={2}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    borderRadius: '6px',
                    background: 'rgba(255, 255, 255, 0.04)',
                    border: '1px solid var(--glass-border)',
                    color: 'var(--text-primary)',
                    fontSize: '0.875rem',
                    outline: 'none',
                    resize: 'vertical',
                  }}
                />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr 1fr', gap: '10px', marginBottom: '14px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: '6px', fontWeight: '500' }}>
                    Date <span style={{ color: 'var(--color-danger)' }}>*</span>
                  </label>
                  <input
                    type="date"
                    value={formDate}
                    onChange={(e) => setFormDate(e.target.value)}
                    style={{
                      width: '100%',
                      padding: '8px 10px',
                      borderRadius: '6px',
                      background: 'rgba(255, 255, 255, 0.04)',
                      border: '1px solid var(--glass-border)',
                      color: 'var(--text-primary)',
                      fontSize: '0.8125rem',
                      outline: 'none',
                    }}
                    required
                  />
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: '6px', fontWeight: '500' }}>
                    Start Time <span style={{ color: 'var(--color-danger)' }}>*</span>
                  </label>
                  <input
                    type="time"
                    value={formStartTime}
                    onChange={(e) => setFormStartTime(e.target.value)}
                    style={{
                      width: '100%',
                      padding: '8px 10px',
                      borderRadius: '6px',
                      background: 'rgba(255, 255, 255, 0.04)',
                      border: '1px solid var(--glass-border)',
                      color: 'var(--text-primary)',
                      fontSize: '0.8125rem',
                      outline: 'none',
                    }}
                    required
                  />
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: '6px', fontWeight: '500' }}>
                    End Time <span style={{ color: 'var(--color-danger)' }}>*</span>
                  </label>
                  <input
                    type="time"
                    value={formEndTime}
                    onChange={(e) => setFormEndTime(e.target.value)}
                    style={{
                      width: '100%',
                      padding: '8px 10px',
                      borderRadius: '6px',
                      background: 'rgba(255, 255, 255, 0.04)',
                      border: '1px solid var(--glass-border)',
                      color: 'var(--text-primary)',
                      fontSize: '0.8125rem',
                      outline: 'none',
                    }}
                    required
                  />
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '16px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: '6px', fontWeight: '500' }}>
                    Location
                  </label>
                  <input
                    type="text"
                    value={formLocation}
                    onChange={(e) => setFormLocation(e.target.value)}
                    placeholder="e.g. Conference Room A / Google Meet"
                    style={{
                      width: '100%',
                      padding: '8px 10px',
                      borderRadius: '6px',
                      background: 'rgba(255, 255, 255, 0.04)',
                      border: '1px solid var(--glass-border)',
                      color: 'var(--text-primary)',
                      fontSize: '0.8125rem',
                      outline: 'none',
                    }}
                  />
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: '6px', fontWeight: '500' }}>
                    Meeting Link
                  </label>
                  <input
                    type="url"
                    value={formLink}
                    onChange={(e) => setFormLink(e.target.value)}
                    placeholder="https://meet.google.com/..."
                    style={{
                      width: '100%',
                      padding: '8px 10px',
                      borderRadius: '6px',
                      background: 'rgba(255, 255, 255, 0.04)',
                      border: '1px solid var(--glass-border)',
                      color: 'var(--text-primary)',
                      fontSize: '0.8125rem',
                      outline: 'none',
                    }}
                  />
                </div>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '20px' }}>
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => setModalOpen(false)}
                  disabled={saving}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={saving}
                >
                  {saving ? 'Saving...' : editingEvent ? 'Save Changes' : 'Create Event'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

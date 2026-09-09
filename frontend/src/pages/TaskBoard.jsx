import React, { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Clock,
  Plus,
  Link2,
  CheckCircle2,
  RotateCcw,
  Edit3,
  Trash2,
  X,
  AlertCircle,
  Calendar,
  Filter,
} from 'lucide-react';
import { useApp } from '../context/AppContext';

const columns = [
  { key: 'pending', label: 'Pending', dotClass: 'pending' },
  { key: 'in_progress', label: 'In Progress', dotClass: 'progress' },
  { key: 'completed', label: 'Completed', dotClass: 'completed' },
];

function getPriorityBadge(priority) {
  const p = (priority || '').toLowerCase();
  const map = {
    urgent: 'danger',
    high: 'danger',
    medium: 'warning',
    low: 'success',
  };
  return map[p] || 'neutral';
}

function getDeadlineInfo(dueDateStr, isCompleted) {
  if (!dueDateStr) return { label: 'No Deadline', color: 'neutral', isOverdue: false };
  const due = new Date(dueDateStr);
  if (isNaN(due.getTime())) return { label: 'No Deadline', color: 'neutral', isOverdue: false };

  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfDue = new Date(due.getFullYear(), due.getMonth(), due.getDate());
  const diffDays = Math.round((startOfDue - startOfToday) / (1000 * 60 * 60 * 24));

  if (!isCompleted && due < now) {
    return { label: 'Overdue', color: 'danger', isOverdue: true };
  }
  if (diffDays === 0) {
    return { label: 'Due Today', color: 'warning', isOverdue: false };
  }
  if (diffDays === 1) {
    return { label: 'Due Tomorrow', color: 'info', isOverdue: false };
  }
  if (diffDays > 1 && diffDays <= 7) {
    return { label: `Due in ${diffDays}d`, color: 'neutral', isOverdue: false };
  }
  return {
    label: due.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
    color: 'neutral',
    isOverdue: false,
  };
}

export default function TaskBoard() {
  const {
    tasks,
    updateTaskStatus,
    completeTask,
    reopenTask,
    deleteTask,
    updateTask,
    createTask,
  } = useApp();
  const navigate = useNavigate();

  const [activeFilter, setActiveFilter] = useState('all'); // all, pending, in_progress, completed, overdue
  const [modalOpen, setModalOpen] = useState(false);
  const [editingTask, setEditingTask] = useState(null);

  // Form State
  const [formTitle, setFormTitle] = useState('');
  const [formDesc, setFormDesc] = useState('');
  const [formDueDate, setFormDueDate] = useState('');
  const [formPriority, setFormPriority] = useState('Medium');
  const [formStatus, setFormStatus] = useState('pending');
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);

  const openNewTaskModal = () => {
    setEditingTask(null);
    setFormTitle('');
    setFormDesc('');
    setFormDueDate('');
    setFormPriority('Medium');
    setFormStatus('pending');
    setFormError('');
    setModalOpen(true);
  };

  const openEditTaskModal = (task) => {
    setEditingTask(task);
    setFormTitle(task.title || task.task_title || '');
    setFormDesc(task.description || '');
    setFormDueDate(task.due_date ? task.due_date.slice(0, 16) : '');
    setFormPriority(task.priority ? task.priority.charAt(0).toUpperCase() + task.priority.slice(1) : 'Medium');
    setFormStatus(task.status || 'pending');
    setFormError('');
    setModalOpen(true);
  };

  const handleFormSubmit = async (e) => {
    e.preventDefault();
    if (!formTitle.trim()) {
      setFormError('Task title is required.');
      return;
    }

    setSaving(true);
    setFormError('');

    try {
      if (editingTask) {
        await updateTask(editingTask.id, {
          title: formTitle.trim(),
          description: formDesc.trim(),
          due_date: formDueDate ? new Date(formDueDate).toISOString() : null,
          priority: formPriority,
          status: formStatus,
        });
      } else {
        const res = await createTask({
          title: formTitle.trim(),
          description: formDesc.trim(),
          due_date: formDueDate ? new Date(formDueDate).toISOString() : null,
          priority: formPriority,
          status: formStatus,
        });
        if (!res.success) {
          throw new Error(res.error || 'Failed to create task.');
        }
      }
      setModalOpen(false);
    } catch (err) {
      setFormError(err.message || 'Failed to save task.');
    } finally {
      setSaving(false);
    }
  };

  const handleToggleComplete = async (task) => {
    try {
      if (task.status === 'completed') {
        await reopenTask(task.id);
      } else {
        await completeTask(task.id);
      }
    } catch (err) {
      console.error('Failed to toggle task status:', err);
    }
  };

  const handleDelete = async (taskId) => {
    if (window.confirm('Are you sure you want to delete this task?')) {
      try {
        await deleteTask(taskId);
      } catch (err) {
        console.error('Failed to delete task:', err);
      }
    }
  };

  const filteredTasks = useMemo(() => {
    return tasks.filter((t) => {
      const isCompleted = t.status === 'completed';
      const isOverdue = t.is_overdue || (!isCompleted && t.due_date && new Date(t.due_date) < new Date());

      if (activeFilter === 'all') return true;
      if (activeFilter === 'overdue') return isOverdue;
      return t.status === activeFilter;
    });
  }, [tasks, activeFilter]);

  const getColumnTasks = (status) => filteredTasks.filter((t) => t.status === status);

  return (
    <div className="taskboard-page page-enter">
      {/* Header */}
      <div className="taskboard-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <h2>Task Board</h2>
          <p style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
            Manage actionable items and deadlines across your emails
          </p>
        </div>
        <div style={{ display: 'flex', gap: '10px' }}>
          <button className="btn btn-primary" onClick={openNewTaskModal}>
            <Plus size={16} /> New Task
          </button>
        </div>
      </div>

      {/* Filter Tabs */}
      <div style={{ display: 'flex', gap: '8px', marginBottom: '24px', flexWrap: 'wrap' }}>
        {[
          { key: 'all', label: 'All Tasks', count: tasks.length },
          { key: 'pending', label: 'Pending', count: tasks.filter((t) => t.status === 'pending').length },
          { key: 'in_progress', label: 'In Progress', count: tasks.filter((t) => t.status === 'in_progress').length },
          { key: 'completed', label: 'Completed', count: tasks.filter((t) => t.status === 'completed').length },
          { key: 'overdue', label: 'Overdue', count: tasks.filter((t) => t.is_overdue || (t.status !== 'completed' && t.due_date && new Date(t.due_date) < new Date())).length },
        ].map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveFilter(tab.key)}
            style={{
              padding: '6px 14px',
              borderRadius: 'var(--radius-full)',
              fontSize: '0.8125rem',
              fontWeight: '500',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              border: activeFilter === tab.key ? '1px solid var(--color-indigo)' : '1px solid var(--glass-border)',
              background: activeFilter === tab.key ? 'rgba(99, 102, 241, 0.15)' : 'rgba(255, 255, 255, 0.02)',
              color: activeFilter === tab.key ? 'var(--color-indigo)' : 'var(--text-secondary)',
              transition: 'all 0.2s',
            }}
          >
            {tab.label}
            <span style={{
              fontSize: '0.6875rem',
              padding: '1px 6px',
              borderRadius: '10px',
              background: activeFilter === tab.key ? 'var(--color-indigo)' : 'rgba(255,255,255,0.06)',
              color: activeFilter === tab.key ? '#fff' : 'var(--text-tertiary)',
            }}>
              {tab.count}
            </span>
          </button>
        ))}
      </div>

      {/* Kanban Board */}
      <div className="kanban-board">
        {columns.map((col) => {
          const columnTasks = getColumnTasks(col.key);
          return (
            <div key={col.key} className="kanban-column">
              <div className="kanban-column-header">
                <div className="kanban-column-title">
                  <span className={`kanban-column-dot ${col.dotClass}`} />
                  {col.label}
                </div>
                <span className="kanban-column-count">{columnTasks.length}</span>
              </div>
              <div className="kanban-column-body">
                {columnTasks.map((task, i) => {
                  const deadline = getDeadlineInfo(task.due_date, task.status === 'completed');
                  const isOverdue = deadline.isOverdue;

                  return (
                    <div
                      key={task.id}
                      className={`task-card animate-fadeIn stagger-${Math.min(i + 1, 5)}`}
                      style={{
                        borderLeft: isOverdue ? '3px solid var(--color-danger)' : undefined,
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                        <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                          <span className={`badge ${getPriorityBadge(task.priority)}`}>
                            {task.priority}
                          </span>
                          {isOverdue && (
                            <span className="badge danger" style={{ fontSize: '0.625rem', padding: '1px 5px' }}>
                              OVERDUE
                            </span>
                          )}
                        </div>

                        {/* Quick Status / Actions */}
                        <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                          <button
                            onClick={() => handleToggleComplete(task)}
                            title={task.status === 'completed' ? 'Reopen task' : 'Complete task'}
                            style={{
                              background: 'none',
                              border: 'none',
                              color: task.status === 'completed' ? 'var(--color-success)' : 'var(--text-tertiary)',
                              cursor: 'pointer',
                              padding: '2px',
                            }}
                          >
                            {task.status === 'completed' ? <RotateCcw size={14} /> : <CheckCircle2 size={14} />}
                          </button>
                          <button
                            onClick={() => openEditTaskModal(task)}
                            title="Edit task"
                            style={{
                              background: 'none',
                              border: 'none',
                              color: 'var(--text-tertiary)',
                              cursor: 'pointer',
                              padding: '2px',
                            }}
                          >
                            <Edit3 size={14} />
                          </button>
                          <button
                            onClick={() => handleDelete(task.id)}
                            title="Delete task"
                            style={{
                              background: 'none',
                              border: 'none',
                              color: 'var(--text-tertiary)',
                              cursor: 'pointer',
                              padding: '2px',
                            }}
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </div>

                      <div className="task-card-title" style={{
                        textDecoration: task.status === 'completed' ? 'line-through' : 'none',
                        color: task.status === 'completed' ? 'var(--text-tertiary)' : 'var(--text-primary)',
                      }}>
                        {task.title}
                      </div>

                      {task.description && (
                        <div className="task-card-desc">{task.description}</div>
                      )}

                      <div className="task-card-footer" style={{ marginTop: '12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span className={`task-card-due ${deadline.color === 'danger' ? 'danger' : ''}`} style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '4px',
                          fontSize: '0.75rem',
                          color: deadline.color === 'danger' ? 'var(--color-danger)' : 'var(--text-tertiary)',
                          fontWeight: deadline.color === 'danger' ? '600' : '400',
                        }}>
                          <Clock size={12} /> {deadline.label}
                        </span>

                        {task.email_id ? (
                          <button
                            onClick={() => navigate('/inbox', { state: { selectEmailId: task.email_id } })}
                            style={{
                              background: 'rgba(99, 102, 241, 0.08)',
                              border: '1px solid rgba(99, 102, 241, 0.2)',
                              borderRadius: '4px',
                              padding: '2px 6px',
                              fontSize: '0.6875rem',
                              color: 'var(--color-indigo)',
                              cursor: 'pointer',
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '4px',
                              textDecoration: 'none',
                            }}
                            title="View source email"
                          >
                            <Link2 size={10} />
                            Source Email
                          </button>
                        ) : (
                          <span style={{ fontSize: '0.6875rem', color: 'var(--text-tertiary)' }}>
                            Manual
                          </span>
                        )}
                      </div>
                    </div>
                  );
                })}

                {columnTasks.length === 0 && (
                  <div style={{
                    padding: '32px 16px',
                    textAlign: 'center',
                    color: 'var(--text-tertiary)',
                    fontSize: '0.8125rem',
                    border: '1px dashed var(--glass-border)',
                    borderRadius: 'var(--radius-md)',
                  }}>
                    No tasks
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Task Creation / Edit Modal */}
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
            maxWidth: '480px',
            padding: '24px',
            boxShadow: '0 20px 40px rgba(0, 0, 0, 0.6)',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h3 style={{ margin: 0, fontSize: '1.1rem', color: 'var(--text-primary)' }}>
                {editingTask ? 'Edit Task' : 'Create New Task'}
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
                  placeholder="e.g. Prepare financial review slides"
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
                  placeholder="Additional context or notes..."
                  rows={3}
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

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '14px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: '6px', fontWeight: '500' }}>
                    Due Date
                  </label>
                  <input
                    type="datetime-local"
                    value={formDueDate}
                    onChange={(e) => setFormDueDate(e.target.value)}
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
                    Priority
                  </label>
                  <select
                    value={formPriority}
                    onChange={(e) => setFormPriority(e.target.value)}
                    style={{
                      width: '100%',
                      padding: '8px 10px',
                      borderRadius: '6px',
                      background: '#1c1f2e',
                      border: '1px solid var(--glass-border)',
                      color: 'var(--text-primary)',
                      fontSize: '0.8125rem',
                      outline: 'none',
                    }}
                  >
                    <option value="Urgent">Urgent</option>
                    <option value="High">High</option>
                    <option value="Medium">Medium</option>
                    <option value="Low">Low</option>
                  </select>
                </div>
              </div>

              {editingTask && (
                <div style={{ marginBottom: '16px' }}>
                  <label style={{ display: 'block', fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: '6px', fontWeight: '500' }}>
                    Status
                  </label>
                  <select
                    value={formStatus}
                    onChange={(e) => setFormStatus(e.target.value)}
                    style={{
                      width: '100%',
                      padding: '8px 10px',
                      borderRadius: '6px',
                      background: '#1c1f2e',
                      border: '1px solid var(--glass-border)',
                      color: 'var(--text-primary)',
                      fontSize: '0.8125rem',
                      outline: 'none',
                    }}
                  >
                    <option value="pending">Pending</option>
                    <option value="in_progress">In Progress</option>
                    <option value="completed">Completed</option>
                    <option value="cancelled">Cancelled</option>
                  </select>
                </div>
              )}

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
                  {saving ? 'Saving...' : editingTask ? 'Save Changes' : 'Create Task'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

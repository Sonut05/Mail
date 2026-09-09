import React, { createContext, useContext, useState, useEffect } from 'react';
import {
  fetchCurrentUser,
  logoutUser,
  fetchDashboardStats,
  fetchEmails,
  fetchEmailById,
  approveReply,
  discardReply,
  fetchTasks,
  updateTask,
  fetchCalendarEvents,
  syncEmails,
  getGoogleLoginUrl,
  loginWithEmail,
  registerWithEmail,
  markEmailAsRead,
  saveResumeProfile,
  deleteResumeProfile,
  getFormAutofill,
  analyzeEmail,
  analyzeEmailsBatch,
  createTask,
  completeTask,
  reopenTask,
  deleteTask,
  createCalendarEvent,
  updateCalendarEvent,
  deleteCalendarEvent,
} from '../services/api';
import {
  mockEmails,
  mockTasks,
  mockCalendarEvents,
  mockDashboardStats,
} from '../data/mockData';

const AppContext = createContext();

// Helper to format ISO datetimes into user-friendly time ago
function formatTimeAgo(dateString) {
  if (!dateString) return '';
  const date = new Date(dateString);
  const now = new Date();
  const seconds = Math.floor((now - date) / 1000);
  
  if (seconds < 60) return 'Just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return 'Yesterday';
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

// Map backend email object to frontend mock-compatible format
function mapBackendEmail(email) {
  const people = [];
  const organizations = [];
  const dates = [];
  const amounts = [];

  if (email.entities) {
    email.entities.forEach(ent => {
      const type = ent.type?.toLowerCase();
      if (type === 'people' || type === 'person') people.push(ent.value);
      else if (type === 'organizations' || type === 'organization' || type === 'org') organizations.push(ent.value);
      else if (type === 'dates' || type === 'date') dates.push(ent.value);
      else if (type === 'amounts' || type === 'money' || type === 'amount') amounts.push(ent.value);
    });
  }

  return {
    id: email.id,
    sender: email.from_address?.split('<')[0]?.trim() || email.from_address || 'Unknown Sender',
    senderEmail: email.from_address?.match(/<([^>]+)>/)?.[1] || email.from_address || '',
    subject: email.subject || '(No Subject)',
    snippet: email.body_text ? email.body_text.slice(0, 120) + '...' : '',
    body: email.body_text || '',
    category: (email.ai_category || email.category || 'other').toLowerCase(),
    priority: (email.ai_priority || email.priority || 'medium').toLowerCase(),
    sentiment: (email.ai_sentiment || email.sentiment || 'neutral').toLowerCase(),
    confidence: email.ai_confidence_score ?? email.confidence ?? 0.85,
    aiImportanceScore: email.ai_importance_score ?? null,
    aiConfidenceScore: email.ai_confidence_score ?? email.confidence ?? 0.85,
    aiKeyPoints: Array.isArray(email.ai_key_points) ? email.ai_key_points : [],
    aiWaitingFor: email.ai_waiting_for || null,
    aiNextAction: email.ai_next_action || null,
    aiReasons: Array.isArray(email.ai_reasons) ? email.ai_reasons : [],
    aiRetryCount: email.ai_retry_count || 0,
    aiLastError: email.ai_last_error || null,
    aiSummary: email.ai_summary || email.summary || 'No summary available.',
    aiStatus: email.ai_status || 'pending',
    aiActionRequired: Boolean(email.ai_action_required),
    aiDeadline: email.ai_deadline || null,
    aiModel: email.ai_model || null,
    aiError: email.ai_error || null,
    suggestedTasks: Array.isArray(email.ai_suggested_tasks) ? email.ai_suggested_tasks : [],
    suggestedEvent: email.ai_suggested_event || null,
    draftReply: email.reply_draft || null,
    autoReplied: email.auto_reply_sent || false,
    read: !email.needs_human_review,
    timestamp: email.received_at,
    timeAgo: formatTimeAgo(email.received_at),
    entities: { people, organizations, dates, amounts }
  };
}

// Map backend task to frontend mock-compatible format
function mapBackendTask(task) {
  return {
    id: task.id,
    title: task.title || task.task_title,
    task_title: task.task_title || task.title,
    description: task.description || '',
    status: (task.status || 'pending').toLowerCase(),
    priority: (task.priority || 'medium').toLowerCase(),
    due_date: task.due_date || null,
    dueDate: task.due_date ? new Date(task.due_date).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : 'No due date',
    is_overdue: Boolean(task.is_overdue),
    isOverdue: Boolean(task.is_overdue),
    completed_at: task.completed_at || null,
    email_id: task.email_id || null,
    sourceEmailId: task.email_id,
    sourceEmailSubject: task.source_email?.subject || task.email_subject || (task.email_id ? 'Source Email' : null),
  };
}

// Map backend calendar event to frontend mock-compatible format
function mapBackendCalendarEvent(evt) {
  const start = new Date(evt.start_date_time || evt.start);
  return {
    id: evt.id,
    title: evt.title,
    description: evt.description || '',
    date: (evt.start_date_time || evt.start)?.split('T')[0] || '',
    time: !isNaN(start.getTime()) ? start.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) : '',
    start: evt.start || evt.start_date_time,
    end: evt.end || evt.end_date_time,
    start_date_time: evt.start_date_time,
    end_date_time: evt.end_date_time,
    duration: evt.end_date_time && !isNaN(start.getTime())
      ? `${Math.round((new Date(evt.end_date_time) - start) / 60000)}m`
      : '30m',
    location: evt.location || 'Online',
    meetingLink: evt.meeting_link || null,
    organizer: evt.organizer || 'Unknown Organizer',
    email_id: evt.email_id || null,
    sourceEmailId: evt.email_id,
    priority: (evt.priority || 'medium').toLowerCase(),
    color: evt.priority === 'high' ? 'danger' : evt.priority === 'medium' ? 'warning' : 'indigo',
    hasReminder: true,
  };
}

// Helper to map category names to CSS colors
function getCategoryColor(category) {
  const map = {
    Support: 'accent',
    Sales: 'indigo',
    Billing: 'success',
    Refund: 'danger',
    Complaint: 'danger',
    Technical: 'accent',
    HR: 'indigo',
    Recruitment: 'indigo',
    Interview: 'purple',
    Internship: 'indigo',
    Meeting: 'purple',
    Project: 'accent',
    Assignment: 'accent',
    University: 'warning',
    Client: 'indigo',
    Finance: 'success',
    Invoice: 'success',
    Subscription: 'success',
    'Security Alert': 'danger',
    Travel: 'purple',
    Event: 'purple',
    Legal: 'danger',
    Personal: 'warning',
    Feedback: 'warning',
    Appreciation: 'warning',
    General: 'neutral',
    Promotion: 'purple',
    Spam: 'neutral',
    Other: 'neutral',
    // Mock fallbacks
    Business: 'indigo',
    Social: 'purple',
    Urgent: 'danger'
  };
  return map[category] || 'neutral';
}

// Function to calculate all statistics dynamically from current emails and tasks
function calculateDashboardStats(emailsList, tasksList) {
  const total = emailsList.length;
  
  // Group by category
  const catMap = {};
  emailsList.forEach(e => {
    const cat = e.category || 'General';
    catMap[cat] = (catMap[cat] || 0) + 1;
  });
  
  const categoryDistribution = Object.keys(catMap).map(name => {
    const count = catMap[name];
    const percentage = total > 0 ? Math.round((count / total) * 100) : 0;
    return {
      name,
      count,
      percentage,
      color: getCategoryColor(name)
    };
  }).sort((a, b) => b.count - a.count);

  // Group by priority
  const priMap = { high: 0, medium: 0, low: 0 };
  emailsList.forEach(e => {
    const p = (e.priority || 'medium').toLowerCase();
    priMap[p] = (priMap[p] || 0) + 1;
  });
  
  const priorityBreakdown = [
    { label: 'High Priority', count: priMap.high, level: 'high' },
    { label: 'Medium Priority', count: priMap.medium, level: 'medium' },
    { label: 'Low Priority', count: priMap.low, level: 'low' },
  ];

  return {
    totalEmails: total,
    autoReplied: emailsList.filter(e => e.autoReplied).length,
    needsReview: emailsList.filter(e => e.needsHumanReview || !e.read).length,
    tasksPending: tasksList.filter(t => t.status !== 'completed').length,
    trends: {
      totalEmails: total > 0 ? '+12%' : '+0%',
      autoReplied: total > 0 ? '+8%' : '+0%',
      needsReview: total > 0 ? '-15%' : '-0%',
      tasksPending: tasksList.filter(t => t.status !== 'completed').length > 0 ? '+3' : '+0',
    },
    categoryDistribution,
    priorityBreakdown,
  };
}

export function AppProvider({ children }) {
  const [user, setUser] = useState(null);
  const [demoMode, setDemoMode] = useState(false);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [emails, setEmails] = useState(mockEmails);
  const [tasks, setTasks] = useState(mockTasks);
  const [calendarEvents, setCalendarEvents] = useState(mockCalendarEvents);
  const [stats, setStats] = useState(calculateDashboardStats(mockEmails, mockTasks));
  const [theme, setTheme] = useState(localStorage.getItem('theme') || 'dark');
  const [savedAccounts, setSavedAccounts] = useState(() => {
    try {
      const stored = localStorage.getItem('mailmind_saved_accounts');
      const parsed = stored ? JSON.parse(stored) : [];
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  });

  const toggleTheme = () => {
    const nextTheme = theme === 'dark' ? 'light' : 'dark';
    setTheme(nextTheme);
    localStorage.setItem('theme', nextTheme);
  };

  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'light') {
      root.classList.add('light-theme');
    } else {
      root.classList.remove('light-theme');
    }
  }, [theme]);

  // Check user session on mount
  useEffect(() => {
    async function initAuth() {
      try {
        const res = await fetchCurrentUser();
        if (res && res.user) {
          setUser(res.user);
          setDemoMode(false);
        } else {
          setUser(null);
          setDemoMode(false);
        }
      } catch (err) {
        console.warn('Backend server unreachable, defaulting to Auth screen');
        setUser(null);
        setDemoMode(false);
      } finally {
        setLoading(false);
      }
    }
    initAuth();
  }, []);

  // Update saved accounts list whenever user changes
  useEffect(() => {
    if (user && user.email) {
      setSavedAccounts((prev) => {
        const exists = prev.some((acc) => acc.email === user.email);
        const updatedAcc = {
          id: user.id,
          email: user.email,
          name: user.name || user.email.split('@')[0],
          picture: user.picture || null,
        };
        let updatedList;
        if (exists) {
          updatedList = prev.map((acc) => (acc.email === user.email ? updatedAcc : acc));
        } else {
          updatedList = [...prev, updatedAcc];
        }
        try {
          localStorage.setItem('mailmind_saved_accounts', JSON.stringify(updatedList));
        } catch (e) {
          console.warn('Failed to save accounts to localStorage', e);
        }
        return updatedList;
      });
    }
  }, [user]);

  // Fetch real data from backend when demoMode changes to false
  useEffect(() => {
    if (!demoMode && user) {
      refreshData().then((emailsList) => {
        // If the database is empty on login, automatically trigger an initial sync!
        if (emailsList && emailsList.length === 0) {
          handleSync();
        }
      });
    } else {
      // Revert to mock data if we go back to demo mode
      setEmails(mockEmails);
      setTasks(mockTasks);
      setCalendarEvents(mockCalendarEvents);
      setStats(calculateDashboardStats(mockEmails, mockTasks));
    }
  }, [demoMode, user]);

  async function refreshData(showGlobalLoader = false) {
    if (demoMode) return [];
    if (showGlobalLoader) {
      setLoading(true);
    }
    try {
      const [emailsRes, tasksRes, eventsRes] = await Promise.all([
        fetchEmails(),
        fetchTasks(),
        fetchCalendarEvents(),
      ]);

      let currentEmails = [];
      let currentTasks = [];

      if (emailsRes && emailsRes.emails) {
        currentEmails = emailsRes.emails.map(mapBackendEmail);
        setEmails(currentEmails);
      }
      if (tasksRes && tasksRes.tasks) {
        currentTasks = tasksRes.tasks.map(mapBackendTask);
        setTasks(currentTasks);
      }
      if (eventsRes && eventsRes.events) {
        setCalendarEvents(eventsRes.events.map(mapBackendCalendarEvent));
      }

      // Calculate stats dynamically from fetched data
      setStats(calculateDashboardStats(currentEmails, currentTasks));
      return currentEmails;
    } catch (err) {
      console.error('Failed to load data from backend:', err);
      return [];
    } finally {
      if (showGlobalLoader) {
        setLoading(false);
      }
    }
  }

  async function handleSync() {
    if (demoMode) {
      // Simulate sync in demo mode
      setSyncing(true);
      await new Promise(resolve => setTimeout(resolve, 1500));
      setSyncing(false);
      return;
    }
    setSyncing(true);
    try {
      await syncEmails();
      await refreshData();
    } catch (err) {
      console.error('Email synchronization failed:', err);
    } finally {
      setSyncing(false);
    }
  }


  const handleApproveReply = async (emailId) => {
    if (demoMode) {
      // Update locally in demo mode
      setEmails(prev => prev.map(e => e.id === emailId ? { ...e, autoReplied: true, read: true } : e));
      return;
    }
    try {
      const res = await approveReply(emailId);
      if (res && !res.error) {
        setEmails(prev => prev.map(e => e.id === emailId ? { ...e, autoReplied: true, read: true } : e));
        await refreshData();
      }
    } catch (err) {
      console.error('Failed to approve reply:', err);
    }
  };

  const handleDiscardReply = async (emailId) => {
    if (demoMode) {
      setEmails(prev => prev.map(e => e.id === emailId ? { ...e, draftReply: null, autoReplied: false } : e));
      return;
    }
    try {
      const res = await discardReply(emailId);
      if (res && !res.error) {
        setEmails(prev => prev.map(e => e.id === emailId ? { ...e, draftReply: null, autoReplied: false } : e));
        await refreshData();
      }
    } catch (err) {
      console.error('Failed to discard reply:', err);
    }
  };

  const handleUpdateTaskStatus = async (taskId, newStatus) => {
    if (demoMode) {
      setTasks(prev => prev.map(t => t.id === taskId ? { ...t, status: newStatus.toLowerCase() } : t));
      return;
    }
    try {
      const res = await updateTask(taskId, { status: newStatus });
      if (res && !res.error) {
        setTasks(prev => prev.map(t => t.id === taskId ? { ...t, status: newStatus.toLowerCase() } : t));
        await refreshData();
      }
    } catch (err) {
      console.error('Failed to update task:', err);
    }
  };

  const handleMarkAsRead = async (emailId) => {
    setEmails(prev => {
      const updated = prev.map(e => e.id === emailId ? { ...e, read: true } : e);
      setStats(calculateDashboardStats(updated, tasks));
      return updated;
    });

    if (demoMode) return;
    try {
      await markEmailAsRead(emailId);
    } catch (err) {
      console.error('Failed to mark email as read:', err);
    }
  };

  const handleAnalyzeEmail = async (emailId) => {
    // Set status to analyzing in local state
    setEmails(prev => prev.map(e => e.id === emailId ? { ...e, aiStatus: 'processing' } : e));
    try {
      const res = await analyzeEmail(emailId);
      if (res && res.email) {
        const mapped = mapBackendEmail(res.email);
        setEmails(prev => prev.map(e => e.id === emailId ? mapped : e));
        return { success: true, email: mapped };
      }
      await refreshData();
      return { success: true };
    } catch (err) {
      console.error('Email analysis failed:', err);
      setEmails(prev => prev.map(e => e.id === emailId ? { ...e, aiStatus: 'failed', aiError: err.message } : e));
      return { success: false, error: err.message };
    }
  };

  const handleAnalyzeBatch = async (limit = 20) => {
    try {
      const res = await analyzeEmailsBatch({ limit });
      await refreshData();
      return res;
    } catch (err) {
      console.error('Batch email analysis failed:', err);
      throw err;
    }
  };

  const handleCreateTask = async (taskData) => {
    try {
      const res = await createTask(taskData);
      if (res && res.task) {
        await refreshData();
        return { success: true, task: res.task };
      }
      return { success: false, error: res?.error || 'Failed to create task.' };
    } catch (err) {
      console.error('Task creation failed:', err);
      return { success: false, error: err.message };
    }
  };

  const handleCreateCalendarEvent = async (eventData) => {
    try {
      const res = await createCalendarEvent(eventData);
      if (res && res.event) {
        await refreshData();
        return { success: true, event: res.event, has_conflict: res.has_conflict, conflicts: res.conflicts };
      }
      return { success: false, error: res?.error || 'Failed to create calendar event.' };
    } catch (err) {
      console.error('Calendar event creation failed:', err);
      return { success: false, error: err.message };
    }
  };

  const handleCompleteTask = async (taskId) => {
    try {
      const res = await completeTask(taskId);
      await refreshData();
      return res;
    } catch (err) {
      console.error('Failed to complete task:', err);
      throw err;
    }
  };

  const handleReopenTask = async (taskId) => {
    try {
      const res = await reopenTask(taskId);
      await refreshData();
      return res;
    } catch (err) {
      console.error('Failed to reopen task:', err);
      throw err;
    }
  };

  const handleDeleteTask = async (taskId) => {
    try {
      const res = await deleteTask(taskId);
      await refreshData();
      return res;
    } catch (err) {
      console.error('Failed to delete task:', err);
      throw err;
    }
  };

  const handleUpdateTask = async (taskId, data) => {
    try {
      const res = await updateTask(taskId, data);
      await refreshData();
      return res;
    } catch (err) {
      console.error('Failed to update task:', err);
      throw err;
    }
  };

  const handleUpdateCalendarEvent = async (eventId, data) => {
    try {
      const res = await updateCalendarEvent(eventId, data);
      await refreshData();
      return res;
    } catch (err) {
      console.error('Failed to update calendar event:', err);
      throw err;
    }
  };

  const handleDeleteCalendarEvent = async (eventId) => {
    try {
      const res = await deleteCalendarEvent(eventId);
      await refreshData();
      return res;
    } catch (err) {
      console.error('Failed to delete calendar event:', err);
      throw err;
    }
  };

  const updateResumeProfile = async (data, file) => {
    if (demoMode) {
      const targetId = data.id || `demo-profile-${Date.now()}`;
      const mockParsed = {
        name: user?.name || "Jane Doe",
        email: user?.email || "jane.doe@gmail.com",
        phone: "+1 (555) 019-2834",
        education: [
          { degree: "Bachelor of Science in Computer Science", institution: "Stanford University", year: "2026" }
        ],
        experience: [
          { role: data.target_role || "Software Engineering Intern", company: "Tech Solutions Inc.", duration: "Summer 2025", summary: "Developed web applications using React and Node.js. Optimized SQL queries to improve latency by 20%." }
        ],
        skills: ["JavaScript", "React", "Node.js", "Python", "SQL", "Git", "HTML/CSS"],
        projects: [
          { title: "AI Mail Assistant", description: "Created an intelligent email parser and autopilot assistant using Gemini API." }
        ]
      };

      const existingProfiles = user?.resume_profiles || [];
      let updatedProfiles = [...existingProfiles];
      const idx = updatedProfiles.findIndex(p => p.id === targetId);
      
      const profileVal = {
        id: targetId,
        target_role: data.target_role,
        min_salary: data.min_salary,
        max_salary: data.max_salary,
        resume_text: file ? file.name : (idx >= 0 ? updatedProfiles[idx].resume_text : "Uploaded Plain Text Resume"),
        resume_parsed_json: mockParsed
      };

      if (idx >= 0) {
        updatedProfiles[idx] = profileVal;
      } else {
        updatedProfiles.push(profileVal);
      }

      setUser(prev => prev ? {
        ...prev,
        resume_profiles: updatedProfiles
      } : null);
      return { success: true, profiles: updatedProfiles };
    }

    try {
      const res = await saveResumeProfile(data, file);
      if (res && res.profiles) {
        setUser(prev => prev ? {
          ...prev,
          resume_profiles: res.profiles
        } : null);
        return { success: true, profiles: res.profiles };
      }
      return { success: false, error: res?.error || 'Failed to save profile.' };
    } catch (err) {
      console.error('Failed to save resume profile:', err);
      return { success: false, error: err.message || 'Failed to save profile.' };
    }
  };

  const removeResumeProfile = async (profileId) => {
    if (demoMode) {
      const existingProfiles = user?.resume_profiles || [];
      const updatedProfiles = existingProfiles.filter(p => p.id !== profileId);
      setUser(prev => prev ? { ...prev, resume_profiles: updatedProfiles } : null);
      return { success: true, profiles: updatedProfiles };
    }

    try {
      const res = await deleteResumeProfile(profileId);
      if (res && res.profiles) {
        setUser(prev => prev ? {
          ...prev,
          resume_profiles: res.profiles
        } : null);
        return { success: true, profiles: res.profiles };
      }
      return { success: false, error: res?.error || 'Failed to delete profile.' };
    } catch (err) {
      console.error('Failed to delete profile:', err);
      return { success: false, error: err.message || 'Failed to delete profile.' };
    }
  };

  const fetchFormAutofillData = async (emailId, profileId = null) => {
    if (demoMode) {
      const profiles = user?.resume_profiles || [];
      const selectedProfile = profileId 
        ? profiles.find(p => p.id === profileId) 
        : (profiles[0] || null);

      const userRole = selectedProfile?.target_role || "Software Engineer";
      const userMinSal = selectedProfile?.min_salary || 90000;
      const userMaxSal = selectedProfile?.max_salary || 120000;

      const isMatch = "software engineer".includes(userRole.toLowerCase()) || "developer".includes(userRole.toLowerCase());
      return {
        is_match: isMatch,
        match_reason: isMatch 
          ? `The job role aligns with your target preference (${userRole}) and Google's standard campus compensation falls within your range.`
          : `The job role does not match your target preference (${userRole}).`,
        form_title: "Google Campus Recruitment 2026 Registration",
        selected_profile_id: selectedProfile?.id || 'demo-profile-1',
        available_profiles: profiles.map(p => ({ id: p.id, target_role: p.target_role })),
        form_fields: [
          { field_name: "Full Name", field_type: "text", value: selectedProfile?.resume_parsed_json?.name || "Jane Doe", source: "Resume" },
          { field_name: "Contact Email", field_type: "text", value: selectedProfile?.resume_parsed_json?.email || "jane.doe@gmail.com", source: "Resume" },
          { field_name: "Graduation Year", field_type: "number", value: "2026", source: "Resume" },
          { field_name: "Target Position", field_type: "select", value: userRole, source: "Preferences" },
          { field_name: "Expected Annual Salary", field_type: "number", value: String(userMinSal + 10000), source: "Preferences" },
          { field_name: "Skills", field_type: "textarea", value: selectedProfile?.resume_parsed_json?.skills?.join(", ") || "JavaScript, React, Node.js, Python, SQL, Git", source: "Resume" },
          { field_name: "Github Profile URL", field_type: "text", value: "https://github.com/janedoe", source: "Derived" }
        ]
      };
    }

    try {
      const res = await getFormAutofill(emailId, profileId);
      return res.autofill;
    } catch (err) {
      console.error('Form auto-fill failed:', err);
      throw err;
    }
  };

  const loginWithGoogle = () => {
    window.location.href = getGoogleLoginUrl();
  };

  const loginWithMock = () => {
    window.location.href = getGoogleLoginUrl() + '?mock=true';
  };

  const handleLoginWithEmail = async (email, password) => {
    try {
      const res = await loginWithEmail(email, password);
      if (res && res.user) {
        setUser(res.user);
        setDemoMode(false);
        return { success: true };
      }
      return { success: false, error: res?.error || 'Failed to authenticate.' };
    } catch (err) {
      console.error('Email login error:', err);
      return { success: false, error: err.message || 'An error occurred.' };
    }
  };

  const handleRegisterWithEmail = async (email, password, name, contactNo) => {
    try {
      const res = await registerWithEmail(email, password, name, contactNo);
      if (res && res.user) {
        setUser(res.user);
        setDemoMode(false);
        return { success: true };
      }
      return { success: false, error: res?.error || 'Failed to register.' };
    } catch (err) {
      console.error('Email registration error:', err);
      return { success: false, error: err.message || 'An error occurred.' };
    }
  };

  const enterDemoMode = () => {
    setUser({ 
      id: 'demo-user-id', 
      email: 'demo@mailmind.ai', 
      name: 'Developer',
      provider: 'demo',
      resume_profiles: [
        {
          id: 'demo-profile-1',
          target_role: 'Software Engineer',
          min_salary: 90000,
          max_salary: 130000,
          resume_text: 'Stanford CS Resume of Jane Doe',
          resume_parsed_json: {
            name: "Jane Doe",
            email: "jane.doe@gmail.com",
            phone: "+1 (555) 019-2834",
            education: [
              { degree: "Bachelor of Science in Computer Science", institution: "Stanford University", year: "2026" }
            ],
            experience: [
              { role: "Software Engineering Intern", company: "Tech Solutions Inc.", duration: "Summer 2025", summary: "Developed web applications using React and Node.js. Optimized SQL queries to improve latency by 20%." }
            ],
            skills: ["JavaScript", "React", "Node.js", "Python", "SQL", "Git", "HTML/CSS"],
            projects: [
              { title: "AI Mail Assistant", description: "Created an intelligent email parser and autopilot assistant using Gemini API." }
            ]
          }
        }
      ]
    });
    setDemoMode(true);
  };

  const logout = async () => {
    if (!demoMode) {
      try {
        await logoutUser();
      } catch (err) {
        console.error('Logout error:', err);
      }
    }
    setUser(null);
    setDemoMode(false);
  };

  return (
    <AppContext.Provider
      value={{
        user,
        demoMode,
        emails,
        tasks,
        calendarEvents,
        stats,
        loading,
        syncing,
        theme,
        toggleTheme,
        login: loginWithGoogle,
        loginWithMock,
        loginWithEmail: handleLoginWithEmail,
        registerWithEmail: handleRegisterWithEmail,
        enterDemoMode,
        logout,
        sync: handleSync,
        approveReplyDraft: handleApproveReply,
        discardReplyDraft: handleDiscardReply,
        updateTaskStatus: handleUpdateTaskStatus,
        completeTask: handleCompleteTask,
        reopenTask: handleReopenTask,
        deleteTask: handleDeleteTask,
        updateTask: handleUpdateTask,
        markEmailAsRead: handleMarkAsRead,
        analyzeEmail: handleAnalyzeEmail,
        analyzeBatch: handleAnalyzeBatch,
        createTask: handleCreateTask,
        createCalendarEvent: handleCreateCalendarEvent,
        updateCalendarEvent: handleUpdateCalendarEvent,
        deleteCalendarEvent: handleDeleteCalendarEvent,
        updateResumeProfile,
        removeResumeProfile,
        fetchFormAutofillData,
        refreshData,
        savedAccounts,
        switchAccount: (acc) => {
          window.location.href = getGoogleLoginUrl() + '?prompt=select_account';
        },
        addAccount: () => {
          window.location.href = getGoogleLoginUrl() + '?prompt=select_account';
        },
        removeSavedAccount: (emailToRemove) => {
          setSavedAccounts((prev) => {
            const filtered = prev.filter((acc) => acc.email !== emailToRemove);
            try {
              localStorage.setItem('mailmind_saved_accounts', JSON.stringify(filtered));
            } catch (e) {}
            return filtered;
          });
        },
      }}
    >
      {children}
    </AppContext.Provider>
  );
}

export function useApp() {
  const context = useContext(AppContext);
  if (!context) {
    throw new Error('useApp must be used within an AppProvider');
  }
  return context;
}

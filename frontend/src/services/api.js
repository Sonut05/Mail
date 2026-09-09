const BASE_URL = import.meta.env.VITE_API_URL || '/api';

async function request(endpoint, options = {}) {
  try {
    const headers = { ...options.headers };
    if (!(options.body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
    }

    const response = await fetch(`${BASE_URL}${endpoint}`, {
      credentials: 'include', // Crucial for session cookies to work cross-origin
      headers,
      ...options,
    });

    if (response.status === 401) {
      // Return a structured unauthorized object instead of throwing
      return { unauthorized: true };
    }

    if (!response.ok) {
      throw new Error(`API Error: ${response.status} ${response.statusText}`);
    }

    return await response.json();
  } catch (error) {
    console.error(`API request failed: ${endpoint}`, error);
    throw error;
  }
}

export function getGoogleLoginUrl() {
  return `${BASE_URL}/auth/google/login`;
}

export function getConnectGoogleUrl() {
  return `${BASE_URL}/auth/google`;
}

export async function fetchMailAccounts() {
  return request('/mail/accounts');
}

export async function disconnectMailAccount(accountId = null) {
  return request('/mail/disconnect', {
    method: 'POST',
    body: JSON.stringify(accountId ? { account_id: accountId } : {}),
  });
}

export async function triggerMailSync(accountId = null) {
  return request('/mail/sync', {
    method: 'POST',
    body: JSON.stringify(accountId ? { account_id: accountId } : {}),
  });
}

export async function triggerIncrementalMailSync(accountId = null) {
  return request('/mail/sync/incremental', {
    method: 'POST',
    body: JSON.stringify(accountId ? { account_id: accountId } : {}),
  });
}

export async function fetchSyncStatus(accountId = null) {
  const query = accountId ? `?account_id=${encodeURIComponent(accountId)}` : '';
  return request(`/mail/sync-status${query}`);
}

export async function fetchCurrentUser() {
  return request('/auth/me');
}

export async function logoutUser() {
  return request('/auth/logout', { method: 'POST' });
}


export async function fetchDashboardStats() {
  return request('/dashboard/stats');
}

export async function fetchEmails(filters = {}) {
  const params = new URLSearchParams(filters).toString();
  return request(`/emails${params ? `?${params}` : ''}`);
}

export async function fetchEmailById(id) {
  return request(`/emails/${id}`);
}

export async function analyzeEmail(id) {
  return request(`/emails/${id}/analyze`, { method: 'POST' });
}

export async function analyzeEmailsBatch(payload = {}) {
  return request('/emails/analyze', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function approveReply(id) {
  return request(`/emails/${id}/approve`, { method: 'POST' });
}

export async function discardReply(id) {
  return request(`/emails/${id}/discard`, { method: 'POST' });
}

export async function fetchTasks(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, val]) => {
    if (val !== undefined && val !== null && val !== '') {
      query.append(key, val);
    }
  });
  const qs = query.toString();
  return request(`/tasks${qs ? `?${qs}` : ''}`);
}

export async function getTaskById(id) {
  return request(`/tasks/${id}`);
}

export async function createTask(taskData) {
  return request('/tasks', {
    method: 'POST',
    body: JSON.stringify(taskData),
  });
}

export async function updateTask(id, data) {
  return request(`/tasks/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export async function completeTask(id) {
  return request(`/tasks/${id}/complete`, { method: 'POST' });
}

export async function reopenTask(id) {
  return request(`/tasks/${id}/reopen`, { method: 'POST' });
}

export async function deleteTask(id) {
  return request(`/tasks/${id}`, { method: 'DELETE' });
}

export async function fetchCalendarEvents() {
  return request('/calendar');
}

export async function getCalendarEventById(id) {
  return request(`/calendar/${id}`);
}

export async function createCalendarEvent(eventData) {
  return request('/calendar', {
    method: 'POST',
    body: JSON.stringify(eventData),
  });
}

export async function updateCalendarEvent(id, data) {
  return request(`/calendar/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export async function deleteCalendarEvent(id) {
  return request(`/calendar/${id}`, { method: 'DELETE' });
}

export async function syncEmails() {
  return request('/emails/sync', { method: 'POST' });
}

export async function loginWithEmail(email, password) {
  return request('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
}

export async function registerWithEmail(email, password, name, contactNo) {
  return request('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ email, password, name, contact_no: contactNo }),
  });
}

export async function generateStandaloneReply(emailBody, tone, customInstructions) {
  return request('/emails/generate-reply', {
    method: 'POST',
    body: JSON.stringify({
      email_body: emailBody,
      tone,
      custom_instructions: customInstructions,
    }),
  });
}

export async function markEmailAsRead(id) {
  return request(`/emails/${id}/read`, { method: 'POST' });
}

export async function fetchResumeProfiles() {
  return request('/resume/profiles');
}

export async function saveResumeProfile(data, file) {
  if (file) {
    const formData = new FormData();
    if (data.id) formData.append('id', data.id);
    if (data.target_role) formData.append('target_role', data.target_role);
    if (data.min_salary !== undefined && data.min_salary !== null) formData.append('min_salary', data.min_salary);
    if (data.max_salary !== undefined && data.max_salary !== null) formData.append('max_salary', data.max_salary);
    formData.append('file', file);
    return request('/resume/profiles', {
      method: 'POST',
      body: formData
    });
  } else {
    return request('/resume/profiles', {
      method: 'POST',
      body: JSON.stringify(data)
    });
  }
}

export async function deleteResumeProfile(profileId) {
  return request(`/resume/profiles/${profileId}`, {
    method: 'DELETE'
  });
}

export async function getFormAutofill(emailId, profileId = null) {
  return request('/resume/auto-fill', {
    method: 'POST',
    body: JSON.stringify({ email_id: emailId, profile_id: profileId })
  });
}

export async function fetchSmartInbox(view = null, limit = 50) {
  const query = new URLSearchParams();
  if (view) query.append('view', view);
  if (limit) query.append('limit', limit);
  const qs = query.toString();
  return request(`/emails/smart-inbox${qs ? `?${qs}` : ''}`);
}

export async function searchEmails(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') {
      query.append(k, v);
    }
  });
  const qs = query.toString();
  return request(`/emails/search${qs ? `?${qs}` : ''}`);
}

export async function fetchContactInsights() {
  return request('/emails/contacts/insights');
}

export async function retryEmailAnalysis(id) {
  return request(`/emails/${id}/retry`, { method: 'POST' });
}

// ── Phase 7: Preferences, Personalization & Privacy ──────────
export async function fetchPreferences() {
  return request('/preferences');
}

export async function updatePreferences(data) {
  return request('/preferences', {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function recordFeedbackSignal(signalType, targetType, targetValue, weight = 1.0) {
  return request('/preferences/signals', {
    method: 'POST',
    body: JSON.stringify({
      signal_type: signalType,
      target_type: targetType,
      target_value: targetValue,
      weight,
    }),
  });
}

export async function clearAIData() {
  return request('/preferences/ai-data', {
    method: 'DELETE',
  });
}

// ── Phase 7: Conversation Threads & Follow-ups ──────────────
export async function fetchThreads(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') {
      query.append(k, v);
    }
  });
  const qs = query.toString();
  return request(`/threads${qs ? `?${qs}` : ''}`);
}

export async function fetchThreadById(threadId) {
  return request(`/threads/${encodeURIComponent(threadId)}`);
}

export async function fetchFollowUps() {
  return request('/threads/follow-ups');
}

export async function fetchStaleThreads() {
  return request('/threads/stale');
}

export async function dismissFollowUp(threadId) {
  return request(`/threads/${encodeURIComponent(threadId)}/dismiss-follow-up`, {
    method: 'POST',
  });
}

// ── Phase 7: Contact / People Intelligence ──────────────────
export async function fetchContactsList(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') {
      query.append(k, v);
    }
  });
  const qs = query.toString();
  return request(`/contacts${qs ? `?${qs}` : ''}`);
}

export async function fetchContactDetail(contactEmail) {
  return request(`/contacts/${encodeURIComponent(contactEmail)}`);
}

// ── Phase 8: Action Center ──────────────────────────────────
export async function fetchActions(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') {
      query.append(k, v);
    }
  });
  const qs = query.toString();
  return request(`/actions${qs ? `?${qs}` : ''}`);
}

export async function snoozeAction(actionId, duration = 'tomorrow', customDate = null) {
  return request(`/actions/${encodeURIComponent(actionId)}/snooze`, {
    method: 'POST',
    body: JSON.stringify({ duration, custom_date: customDate }),
  });
}

export async function dismissAction(actionId) {
  return request(`/actions/${encodeURIComponent(actionId)}/dismiss`, {
    method: 'POST',
  });
}

export async function completeAction(actionId) {
  return request(`/actions/${encodeURIComponent(actionId)}/complete`, {
    method: 'POST',
  });
}

export async function executeBulkAction(action, itemIds, itemType = 'email', options = {}) {
  return request('/actions/bulk', {
    method: 'POST',
    body: JSON.stringify({
      action,
      item_ids: itemIds,
      item_type: itemType,
      options,
    }),
  });
}

// ── Phase 8: Notification Center ────────────────────────────
export async function fetchNotifications(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') {
      query.append(k, v);
    }
  });
  const qs = query.toString();
  return request(`/notifications${qs ? `?${qs}` : ''}`);
}

export async function fetchUnreadNotificationsCount() {
  return request('/notifications/unread-count');
}

export async function markNotificationRead(notifId) {
  return request(`/notifications/${encodeURIComponent(notifId)}/read`, {
    method: 'POST',
  });
}

export async function markAllNotificationsRead() {
  return request('/notifications/read-all', {
    method: 'POST',
  });
}

export async function dismissNotification(notifId) {
  return request(`/notifications/${encodeURIComponent(notifId)}/dismiss`, {
    method: 'POST',
  });
}

// ── Phase 8: Daily AI Digest ────────────────────────────────
export async function fetchDailyDigest(date = null, timezone = 'UTC') {
  const query = new URLSearchParams();
  if (date) query.append('date', date);
  if (timezone) query.append('timezone', timezone);
  const qs = query.toString();
  return request(`/digest${qs ? `?${qs}` : ''}`);
}

// ── Phase 8: Productivity Analytics ─────────────────────────
export async function fetchProductivityAnalytics(period = '30d') {
  return request(`/analytics/productivity?period=${encodeURIComponent(period)}`);
}

// ── Phase 8: Saved Searches ─────────────────────────────────
export async function fetchSavedSearches() {
  return request('/searches');
}

export async function createSavedSearch(name, query) {
  return request('/searches', {
    method: 'POST',
    body: JSON.stringify({ name, query }),
  });
}

export async function deleteSavedSearch(searchId) {
  return request(`/searches/${encodeURIComponent(searchId)}`, {
    method: 'DELETE',
  });
}

// ── Phase 8: Meeting Conflict Detection ─────────────────────
export async function checkMeetingConflict(start, end = null, excludeId = null) {
  return request('/calendar/check-conflict', {
    method: 'POST',
    body: JSON.stringify({ start, end, exclude_id: excludeId }),
  });
}


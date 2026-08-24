// --- Studiamo Settings & Statistics Module ---

async function loadStats() {
    try {
        try {
            const dashData = await fetchAPI('/api/dashboard');
            if (dashData && dashData.user) {
                currentUserStats = dashData.user;
                if (typeof updateHeaderStats === 'function') {
                    updateHeaderStats();
                }
            }
        } catch (e) {
            console.warn("Could not refresh user stats for dashboard:", e);
        }

        const stats = await fetchAPI('/api/stats');

        const usageWarningEl = document.getElementById('ai-usage-warning');
        if (usageWarningEl && stats.usage_status) {
            if (stats.usage_status.show_warning) {
                document.getElementById('ai-usage-remaining-pct').textContent = stats.usage_status.percent_remaining;
                usageWarningEl.classList.remove('hidden');
                usageWarningEl.classList.add('flex');
            } else {
                usageWarningEl.classList.add('hidden');
                usageWarningEl.classList.remove('flex');
            }
        }

        const tbody = document.getElementById('ai-logs-tbody');
        if (tbody) {
            tbody.innerHTML = '';
            const callsEl = document.getElementById('stats-total-calls');
            if (callsEl) callsEl.textContent = `${stats.total_calls || 0} Requests`;
            
            if (!stats.logs || stats.logs.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4" class="p-4 text-center text-stone-500">No API calls recorded yet.</td></tr>';
            } else {
                stats.logs.forEach(log => {
                    const date = parseDate(log.timestamp);
                    tbody.innerHTML += `
                        <tr class="border-b border-stone-200 hover:bg-stone-100 text-stone-700">
                            <td class="p-3 font-mono text-xs">${date.toISOString().replace('T', ' ').substring(0, 19)}</td>
                            <td class="p-3 capitalize text-xs">${(log.action_type || '').replace('_', ' ')}</td>
                            <td class="p-3 text-xs font-mono text-amber-700">${log.model || 'gemini'}</td>
                            <td class="p-3 text-right font-semibold font-mono text-xs">${(log.prompt_tokens || 0) + (log.completion_tokens || 0)}</td>
                        </tr>
                    `;
                });
            }
        }
        
        const xp = currentUserStats.xp || 0;
        const calcLevel = Math.floor(Math.sqrt(xp / 50)) + 1;
        const level = Math.max(currentUserStats.level || 1, calcLevel);
        
        const curLevelXP = 50 * Math.pow(level - 1, 2);
        const nextLevelXP = 50 * Math.pow(level, 2);
        const xpInLevel = xp - curLevelXP;
        const xpRequiredForNext = Math.max(1, nextLevelXP - curLevelXP);
        const progressPct = Math.min(100, Math.max(0, (xpInLevel / xpRequiredForNext) * 100));
        
        const lvlEl = document.getElementById('stats-level-val');
        const xpEl = document.getElementById('stats-xp-val');
        const xpNextEl = document.getElementById('stats-xp-next-val');
        const xpBar = document.getElementById('stats-xp-progress');
        const streakEl = document.getElementById('stats-streak-val');
        
        if (lvlEl) lvlEl.textContent = level;
        if (xpEl) xpEl.textContent = `${xp} Total XP`;
        if (xpNextEl) xpNextEl.textContent = `${Math.max(0, nextLevelXP - xp)} XP for Level ${level + 1}`;
        if (xpBar) xpBar.style.width = `${progressPct}%`;
        if (streakEl) streakEl.textContent = currentUserStats.streak || 0;
        
        const badgesGrid = document.getElementById('badges-grid');
        if (badgesGrid) {
            badgesGrid.innerHTML = '';
            const badgeDetails = {
                "5-Day Streak": { icon: "flame", desc: "Completed quizzes 5 days in a row.", color: "text-amber-500 border-amber-500/20 bg-amber-500/5" },
                "10-Day Streak": { icon: "flame", desc: "Completed quizzes 10 days in a row.", color: "text-amber-400 border-amber-400/20 bg-amber-400/5" },
                "SRS Stage 5 Master": { icon: "award", desc: "Successfully promoted a card to SRS level 5.", color: "text-amber-400 border-amber-500/20 bg-amber-500/5" },
                "Video Collector": { icon: "folder-open", desc: "Imported 10 or more video resources.", color: "text-emerald-400 border-emerald-500/20 bg-emerald-500/5" },
                "Renaissance Learner": { icon: "book-open", desc: "Explored 3 or more distinct topics.", color: "text-amber-400 border-amber-500/20 bg-amber-500/5" }
            };
            
            const unlockedBadgesList = typeof currentUserStats.badges === 'string' 
                ? JSON.parse(currentUserStats.badges || '[]') 
                : (currentUserStats.badges || []);
                
            Object.keys(badgeDetails).forEach(name => {
                const detail = badgeDetails[name];
                const isUnlocked = unlockedBadgesList.includes(name);
                const opacityClass = isUnlocked ? 'opacity-100 border-amber-200 bg-amber-500/5' : 'opacity-40 filter grayscale border-stone-200';
                
                badgesGrid.innerHTML += `
                    <div class="flex items-center space-x-3 p-3 bg-stone-50 border rounded-xl transition hover:border-stone-200 ${opacityClass}">
                        <div class="p-2 rounded-lg border ${detail.color} shrink-0">
                            <i data-lucide="${detail.icon}" class="w-5 h-5"></i>
                        </div>
                        <div class="min-w-0 flex-grow">
                            <span class="block text-xs font-bold text-stone-900">${name}</span>
                            <p class="text-[10px] text-stone-500 truncate" title="${detail.desc}">${detail.desc}</p>
                        </div>
                    </div>
                `;
            });
        }
        
        try {
            const lb = await fetchAPI('/api/leaderboard');
            const lbContainer = document.getElementById('leaderboard-container');
            if (lbContainer && lb.rankings) {
                lbContainer.innerHTML = '';
                let lastRank = 0;
                lb.rankings.forEach((entry, idx) => {
                    const rank = entry.rank !== undefined ? entry.rank : (idx + 1);
                    if (lastRank > 0 && rank > lastRank + 1) {
                        lbContainer.innerHTML += `
                            <div class="flex items-center justify-center py-1 px-3 bg-stone-100 border border-dashed border-stone-200 rounded-xl my-1">
                                <span class="text-[11px] font-semibold text-stone-500 tracking-widest">• • •</span>
                            </div>
                        `;
                    }
                    lastRank = rank;

                    const isMe = !!entry.is_self;
                    const medal = rank === 1 ? '#1' : rank === 2 ? '#2' : rank === 3 ? '#3' : `${rank}`;
                    const initials = (entry.display_name || '?').substring(0, 2).toUpperCase();
                    const weeklyXpText = `${entry.weekly_xp || 0} XP`;

                    lbContainer.innerHTML += `
                        <div class="flex items-center justify-between p-3 ${isMe ? 'bg-amber-500/15 border border-amber-500/40' : 'bg-[#fbf8f2] border border-[#e7dfd3]'} rounded-xl transition hover:border-amber-500/40">
                            <div class="flex items-center space-x-3 min-w-0">
                                <span class="font-bold text-xs w-6 text-center shrink-0 ${rank <= 3 ? 'text-amber-800 font-extrabold' : 'text-stone-500'}">${medal}</span>
                                <div class="w-8 h-8 rounded-full ${isMe ? 'bg-amber-500/25 text-amber-900 border border-amber-500/40' : 'bg-[#f3ebd9] text-stone-700 border border-[#dfd5c5]'} flex items-center justify-center font-bold text-xs shrink-0">${initials}</div>
                                <div class="min-w-0">
                                    <span class="font-bold text-sm ${isMe ? 'text-amber-950 font-bold' : 'text-stone-800'} block truncate">${entry.display_name}${isMe ? ' (You)' : ''}</span>
                                    <p class="text-[10px] text-stone-500 flex items-center space-x-1 truncate">
                                        <span class="flex items-center space-x-1"><i data-lucide="flame" class="w-3 h-3 text-amber-500 shrink-0"></i><span>${entry.streak} day streak</span></span>
                                        <span>·</span>
                                        <span class="text-amber-800 font-medium">Lvl ${entry.level}</span>
                                    </p>
                                </div>
                            </div>
                            <div class="text-right shrink-0">
                                <span class="text-xs font-extrabold ${isMe ? 'text-amber-800' : 'text-stone-700'}">${weeklyXpText}</span>
                                <span class="block text-[9px] text-stone-500 font-medium">${entry.xp || 0} Total XP</span>
                            </div>
                        </div>
                    `;
                });
                if (typeof renderIcons === 'function') renderIcons();
                else if (typeof lucide !== 'undefined') lucide.createIcons();
            }
        } catch (e) {
            console.error("Leaderboard load failed:", e);
        }
        
        try {
            const historyData = await fetchAPI('/api/stats/history');
            const attEl = document.getElementById('analytics-total-attempts');
            const remEl = document.getElementById('analytics-remembered');
            const forgEl = document.getElementById('analytics-forgot');
            const accEl = document.getElementById('analytics-accuracy');
            
            const ratioEl = document.getElementById('stats-ratio-val');
            const accBadgeEl = document.getElementById('stats-accuracy-badge');
            const ratioSubEl = document.getElementById('stats-ratio-subtext');
            
            if (attEl) attEl.textContent = historyData.total_attempts;
            if (remEl) remEl.textContent = historyData.remembered;
            if (forgEl) forgEl.textContent = historyData.forgot;
            if (accEl) accEl.textContent = `${historyData.accuracy_pct}%`;
            
            if (ratioEl) ratioEl.textContent = `${historyData.remembered} / ${historyData.forgot}`;
            if (accBadgeEl) accBadgeEl.textContent = `${historyData.accuracy_pct}%`;
            if (ratioSubEl) ratioSubEl.textContent = `${historyData.remembered} Right · ${historyData.forgot} Wrong`;
            
            window._analyticsAttemptsRaw = historyData.recent_attempts || [];
            renderAnalyticsHistory();
        } catch (err) {
            console.error("Failed to load in-depth analytics history:", err);
        }
        
        renderIcons();
    } catch (e) {
        console.error("Stats loading error:", e);
    }
}

async function loadSettings() {
    window._settingsLoading = true;
    try {
        const configData = await fetchAPI('/api/settings');
        window._lastSettingsConfig = configData;

        const geminiHint = document.getElementById('settings-gemini-key-hint');
        const teleHint = document.getElementById('settings-telegram-token-hint');
        if (geminiHint) geminiHint.textContent = configData.gemini_api_key_masked ? `Saved: ${configData.gemini_api_key_masked}` : 'Not set';
        if (teleHint) teleHint.textContent = configData.telegram_bot_token_masked ? `Saved: ${configData.telegram_bot_token_masked}` : 'Not set (optional)';
        
        const gInput = document.getElementById('settings-gemini-key');
        const tInput = document.getElementById('settings-telegram-token');
        if (gInput) gInput.value = '';
        if (tInput) tInput.value = '';
        
        const teleChat = document.getElementById('settings-telegram-chat');
        const baseUrl = document.getElementById('settings-base-url');
        if (teleChat) teleChat.value = configData.telegram_chat_id || '';
        if (baseUrl) baseUrl.value = configData.base_url || '';
        
        const unField = document.getElementById('profile-username');
        if (unField) unField.value = configData.username || activeUsername;

        if (configData.display_name) {
            const dnField = document.getElementById('profile-display-name');
            if (dnField) dnField.value = configData.display_name;
        }
        
        const defaults = configData.defaults || {};
        
        const s1 = document.getElementById('srs-stage-1');
        const s2 = document.getElementById('srs-stage-2');
        const s3 = document.getElementById('srs-stage-3');
        const s4 = document.getElementById('srs-stage-4');
        const s5 = document.getElementById('srs-stage-5');
        const intervals = configData.srs_intervals || {};
        if (s1) { s1.placeholder = defaults.srs_stage_1 || '1'; s1.value = configData.has_custom_srs ? (configData.srs_stage_1 !== undefined ? configData.srs_stage_1 : '') : ''; }
        if (s2) { s2.placeholder = defaults.srs_stage_2 || '3'; s2.value = configData.has_custom_srs ? (configData.srs_stage_2 !== undefined ? configData.srs_stage_2 : '') : ''; }
        if (s3) { s3.placeholder = defaults.srs_stage_3 || '7'; s3.value = configData.has_custom_srs ? (configData.srs_stage_3 !== undefined ? configData.srs_stage_3 : '') : ''; }
        if (s4) { s4.placeholder = defaults.srs_stage_4 || '14'; s4.value = configData.has_custom_srs ? (configData.srs_stage_4 !== undefined ? configData.srs_stage_4 : '') : ''; }
        if (s5) { s5.placeholder = defaults.srs_stage_5 || '30'; s5.value = configData.has_custom_srs ? (configData.srs_stage_5 !== undefined ? configData.srs_stage_5 : '') : ''; }
        
        const notifEnabledSwitch = document.getElementById('settings-notifications-enabled');
        const isNotifEnabled = configData.notifications_enabled !== undefined ? !!configData.notifications_enabled : true;
        if (notifEnabledSwitch) notifEnabledSwitch.checked = isNotifEnabled;
        toggleNotificationsMasterSwitch(isNotifEnabled);

        const capStages = document.getElementById('settings-cap-stages');
        if (capStages) capStages.checked = !!configData.cap_stages_by_importance;
        toggleCapStagesPanel();

        const repeatStage5Chk = document.getElementById('settings-repeat-stage-5');
        if (repeatStage5Chk) repeatStage5Chk.checked = !!configData.enable_stage_5_repetition;
        const repeatIntervalInput = document.getElementById('srs-stage-5-repeat-interval');
        if (repeatIntervalInput) repeatIntervalInput.value = configData.stage_5_repeat_interval !== undefined ? configData.stage_5_repeat_interval : 30;
        toggleStage5RepeatPanel();
        
        if (configData.srs_multipliers) {
            const m1 = document.getElementById('srs-mult-1');
            const m2 = document.getElementById('srs-mult-2');
            const m3 = document.getElementById('srs-mult-3');
            const m4 = document.getElementById('srs-mult-4');
            const m5 = document.getElementById('srs-mult-5');
            if (m1) { m1.placeholder = '4.0'; m1.value = configData.has_custom_multipliers ? configData.srs_multipliers.multiplier_1 : ''; }
            if (m2) { m2.placeholder = '2.5'; m2.value = configData.has_custom_multipliers ? configData.srs_multipliers.multiplier_2 : ''; }
            if (m3) { m3.placeholder = '1.5'; m3.value = configData.has_custom_multipliers ? configData.srs_multipliers.multiplier_3 : ''; }
            if (m4) { m4.placeholder = '1.0'; m4.value = configData.has_custom_multipliers ? configData.srs_multipliers.multiplier_4 : ''; }
            if (m5) { m5.placeholder = '0.7'; m5.value = configData.has_custom_multipliers ? configData.srs_multipliers.multiplier_5 : ''; }
        }
        
        if (configData.srs_caps) {
            const c1 = document.getElementById('srs-cap-1');
            const c2 = document.getElementById('srs-cap-2');
            const c3 = document.getElementById('srs-cap-3');
            const c4 = document.getElementById('srs-cap-4');
            const c5 = document.getElementById('srs-cap-5');
            if (c1) { c1.placeholder = '2'; c1.value = configData.has_custom_caps ? configData.srs_caps.cap_1 : ''; }
            if (c2) { c2.placeholder = '3'; c2.value = configData.has_custom_caps ? configData.srs_caps.cap_2 : ''; }
            if (c3) { c3.placeholder = '4'; c3.value = configData.has_custom_caps ? configData.srs_caps.cap_3 : ''; }
            if (c4) { c4.placeholder = '5'; c4.value = configData.has_custom_caps ? configData.srs_caps.cap_4 : ''; }
            if (c5) { c5.placeholder = '5'; c5.value = configData.has_custom_caps ? configData.srs_caps.cap_5 : ''; }
        }

        if (configData.question_counts) {
            const sc1 = document.getElementById('star-count-1');
            const sc2 = document.getElementById('star-count-2');
            const sc3 = document.getElementById('star-count-3');
            const sc4 = document.getElementById('star-count-4');
            const sc5 = document.getElementById('star-count-5');
            if (sc1) { sc1.placeholder = defaults.star_count_1 || '2'; sc1.value = configData.has_custom_question_counts ? configData.question_counts.count_1 : ''; }
            if (sc2) { sc2.placeholder = defaults.star_count_2 || '3'; sc2.value = configData.has_custom_question_counts ? configData.question_counts.count_2 : ''; }
            if (sc3) { sc3.placeholder = defaults.star_count_3 || '5'; sc3.value = configData.has_custom_question_counts ? configData.question_counts.count_3 : ''; }
            if (sc4) { sc4.placeholder = defaults.star_count_4 || '8'; sc4.value = configData.has_custom_question_counts ? configData.question_counts.count_4 : ''; }
            if (sc5) { sc5.placeholder = defaults.star_count_5 || '12'; sc5.value = configData.has_custom_question_counts ? configData.question_counts.count_5 : ''; }
        }
        
        const prefHour = document.getElementById('settings-preferred-hour');
        if (prefHour) prefHour.value = configData.preferred_hour !== undefined ? configData.preferred_hour : -1;

        const rmSel = document.getElementById('settings-review-mode');
        if (rmSel && configData.review_mode) rmSel.value = configData.review_mode;

        // Channel toggles : each independent, each expands its own panel
        const notifTelegram = document.getElementById('settings-notify-telegram');
        if (notifTelegram) notifTelegram.checked = !!configData.notify_telegram;
        toggleTelegramNotifyPanel(!!configData.notify_telegram);

        const notifPush = document.getElementById('settings-notify-push');
        if (notifPush) notifPush.checked = !!configData.notify_push;
        togglePushNotifyPanel(!!configData.notify_push);

        const notifEmail = document.getElementById('settings-notify-email');
        if (notifEmail) notifEmail.checked = !!configData.notify_email;
        toggleEmailNotifyPanel(!!configData.notify_email);

        const emailAddrEl = document.getElementById('notify-email-address');
        if (emailAddrEl) emailAddrEl.textContent = configData.notification_email || '-';

        // Category checkboxes (default on : matches pre-existing unfiltered behavior)
        const catQuizzes = document.getElementById('settings-notify-cat-quizzes');
        if (catQuizzes) catQuizzes.checked = configData.notify_cat_quizzes !== undefined ? !!configData.notify_cat_quizzes : true;
        const catStreak = document.getElementById('settings-notify-cat-streak');
        if (catStreak) catStreak.checked = configData.notify_cat_streak !== undefined ? !!configData.notify_cat_streak : true;
        const catInactivity = document.getElementById('settings-notify-cat-inactivity');
        if (catInactivity) catInactivity.checked = configData.notify_cat_inactivity !== undefined ? !!configData.notify_cat_inactivity : true;

        updateTelegramConnectStatus(configData);
        updateBrowserNotificationStatus();

        // Restore leaderboard hidden toggle
        const lbToggle = document.getElementById('leaderboard-hidden-toggle');
        if (lbToggle) lbToggle.checked = !!configData.leaderboard_hidden;

        // Restore voice engine settings from server/localStorage
        if (configData.voice_engine) {
            localStorage.setItem('studiamo_voice_engine', configData.voice_engine);
        }
        if (configData.voice_speed !== undefined && configData.voice_speed !== null) {
            localStorage.setItem('studiamo_voice_speed', configData.voice_speed);
        }
        initVoiceSettings();

        // Subscription status box (cloud only : see .cloud-only in index.html).
        // Delegated to billing.js so every Lemon Squeezy status is covered: an earlier
        // version here branched only on 'active' vs tester, so 'cancelled' and 'past_due'
        // both fell through to "no subscription yet", telling paying customers the
        // opposite of the truth.
        if (typeof renderSubscriptionCard === 'function') {
            renderSubscriptionCard(configData);
        }

        // Google SSO Link Status UI
        const googleBadge = document.getElementById('google-linked-badge');
        const googleBtn = document.getElementById('btn-link-google-acc');
        const googleEmailEl = document.getElementById('google-linked-email');

        if (configData.google_linked) {
            if (googleBadge) googleBadge.classList.remove('hidden');
            if (googleBtn) googleBtn.classList.add('hidden');
            if (googleEmailEl) googleEmailEl.textContent = `Linked to Google (${configData.google_email || 'Verified'})`;
        } else {
            if (googleBadge) googleBadge.classList.add('hidden');
            if (googleBtn) googleBtn.classList.remove('hidden');
        }

        // Handle URL notification after OAuth redirect
        const urlParams = new URLSearchParams(window.location.search);
        if (urlParams.get('google_linked') === 'true') {
            showToast('Google account linked successfully!', 'saved');
            window.history.replaceState({}, document.title, window.location.pathname);
        }
        if (urlParams.get('google_error') === 'already_linked') {
            showToast('That Google account already belongs to another Studiamo account.', 'error');
            window.history.replaceState({}, document.title, window.location.pathname);
        }
        
    } catch (e) {
        console.error("Settings load error:", e);
    } finally {
        window._settingsLoading = false;
    }
}

function toggleCapStagesPanel() {
    const chk = document.getElementById('settings-cap-stages');
    const panel = document.getElementById('settings-cap-stages-panel') || document.getElementById('panel-cap-stages');
    if (!chk || !panel) return;
    if (chk.checked) {
        panel.classList.remove('hidden');
    } else {
        panel.classList.add('hidden');
    }
}

function toggleStage5RepeatPanel() {
    const chk = document.getElementById('settings-repeat-stage-5');
    const panel = document.getElementById('settings-stage-5-repeat-panel');
    if (!chk || !panel) return;
    if (chk.checked) {
        panel.classList.remove('hidden');
    } else {
        panel.classList.add('hidden');
    }
}

function toggleSrsConfigPanel() {
    const body = document.getElementById('srs-config-body');
    const icon = document.getElementById('srs-config-toggle-icon');
    if (!body) return;

    const isHidden = body.classList.contains('hidden');
    if (isHidden) {
        body.classList.remove('hidden');
        if (icon) icon.style.transform = 'rotate(180deg)';
    } else {
        body.classList.add('hidden');
        if (icon) icon.style.transform = 'rotate(0deg)';
    }
}

function togglePwdVisibility(inputId, btn) {
    const input = document.getElementById(inputId);
    if (!input) return;
    const isHidden = input.type === 'password';
    input.type = isHidden ? 'text' : 'password';
    const icon = btn.querySelector('i');
    if (icon) {
        icon.setAttribute('data-lucide', isHidden ? 'eye-off' : 'eye');
        renderIcons();
    }
}

async function handleProfileSave(event) {
    event.preventDefault();
    const newUsername = document.getElementById('profile-username')?.value.trim();
    const displayName = document.getElementById('profile-display-name')?.value.trim();
    const geminiKey = document.getElementById('settings-gemini-key')?.value.trim();

    const btnSave = event?.target?.querySelector?.('button[type="submit"]') || document.getElementById('btn-save-profile');
    let origSaveContent = '';
    if (btnSave) {
        origSaveContent = btnSave.innerHTML;
        const icon = btnSave.querySelector('i, svg');
        if (icon) {
            icon.outerHTML = `<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin text-stone-900 shrink-0"></i>`;
        }
        btnSave.classList.add('opacity-75', 'cursor-wait');
        btnSave.disabled = true;
        if (typeof renderIcons === 'function') renderIcons();
    }

    const fd = new FormData();
    if (newUsername && newUsername !== activeUsername) fd.append('new_username', newUsername);
    if (displayName !== undefined) fd.append('display_name', displayName);
    // No is_anonymous field. The leaderboard toggle is saved by setLeaderboardHidden()
    // through POST /api/settings, which writes user_profile.leaderboard_hidden, and that
    // column is what the leaderboard actually reads. Sending it here as well stored a
    // second copy in the per-user config that nothing ever consulted.
    if (geminiKey) fd.append('gemini_api_key', geminiKey);

    try {
        const res = await fetchAPI('/api/settings/profile', { method: 'POST', body: fd });
        if (res.username && res.username !== activeUsername) {
            activeUsername = res.username;
            localStorage.setItem('active_username', res.username);
            document.cookie = `username=${res.username}; path=/; max-age=31536000`;
        }
        showToast(`Profile saved successfully!`, 'saved');
        if (typeof loadStats === 'function') loadStats();
        if (typeof loadSettings === 'function') loadSettings();
    } catch (e) {
        showToast('Failed to save profile: ' + e.message, 'failed');
    } finally {
        if (btnSave) {
            btnSave.innerHTML = origSaveContent;
            btnSave.classList.remove('opacity-75', 'cursor-wait');
            btnSave.disabled = false;
            if (typeof renderIcons === 'function') renderIcons();
        }
    }
}

function openChangePasswordModal() {
    const modal = document.getElementById('overlay-change-password-modal');
    if (!modal) return;
    const cur = document.getElementById('modal-current-password');
    const np = document.getElementById('modal-new-password');
    const cp = document.getElementById('modal-confirm-password');
    const err = document.getElementById('change-pwd-error');
    if (cur) cur.value = '';
    if (np) np.value = '';
    if (cp) cp.value = '';
    if (err) {
        err.textContent = '';
        err.classList.add('hidden');
    }
    openOverlay('overlay-change-password-modal', closeChangePasswordModal);
    if (typeof renderIcons === 'function') renderIcons();
}

function closeChangePasswordModal() {
    const modal = document.getElementById('overlay-change-password-modal');
    if (modal) modal.classList.add('hidden');
    closeOverlay('overlay-change-password-modal');
}

async function handleChangePassword(event) {
    event.preventDefault();
    const cur = document.getElementById('modal-current-password')?.value || '';
    const np = document.getElementById('modal-new-password')?.value || '';
    const cp = document.getElementById('modal-confirm-password')?.value || '';
    const err = document.getElementById('change-pwd-error');
    const btn = document.getElementById('btn-submit-change-pwd');

    if (err) {
        err.textContent = '';
        err.classList.add('hidden');
    }

    if (!np.trim()) {
        if (err) {
            err.textContent = 'New password cannot be blank.';
            err.classList.remove('hidden');
        }
        return;
    }

    if (np !== cp) {
        if (err) {
            err.textContent = 'New passwords do not match.';
            err.classList.remove('hidden');
        }
        return;
    }

    let origBtnContent = '';
    if (btn) {
        origBtnContent = btn.innerHTML;
        btn.innerHTML = `<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin text-stone-900 shrink-0 inline-block"></i> Updating...`;
        btn.disabled = true;
        if (typeof renderIcons === 'function') renderIcons();
    }

    const fd = new FormData();
    fd.append('old_password', cur);
    fd.append('new_password', np.trim());

    try {
        await fetchAPI('/api/settings/profile', { method: 'POST', body: fd });
        closeChangePasswordModal();
        showToast('Password updated successfully!', 'saved');
    } catch (e) {
        if (err) {
            err.textContent = e.message || 'Failed to update password.';
            err.classList.remove('hidden');
        } else {
            showToast('Failed to update password: ' + e.message, 'failed');
        }
    } finally {
        if (btn) {
            btn.innerHTML = origBtnContent || 'Update Password';
            btn.disabled = false;
            if (typeof renderIcons === 'function') renderIcons();
        }
    }
}

async function setLeaderboardHidden(hidden) {
    if (_settingsAutosaveTimer) clearTimeout(_settingsAutosaveTimer);
    try {
        const fd = new FormData();
        fd.append('leaderboard_hidden', hidden ? 'true' : 'false');
        await fetchAPI('/api/settings', { method: 'POST', body: fd });
        if (typeof loadStats === 'function') loadStats();
    } catch (e) {
        console.error('Failed to set leaderboard visibility:', e);
    }
}

let _settingsAutosaveTimer = null;


function showSettingsIndicator(text, state = 'saved') {
    showToast(text, state);
}

function _scheduleSettingsAutosave() {
    if (window._settingsLoading) return;
    showToast('Saving...', 'saving');
    if (_settingsAutosaveTimer) clearTimeout(_settingsAutosaveTimer);
    _settingsAutosaveTimer = setTimeout(() => _submitSettings(false), 1200);
}


async function _submitSettings(silent = true) {
    const formData = new FormData();
    const geminiKey = document.getElementById('settings-gemini-key')?.value;
    const teleToken = document.getElementById('settings-telegram-token')?.value;
    const teleChat = document.getElementById('settings-telegram-chat')?.value;
    const baseUrl = document.getElementById('settings-base-url')?.value;

    if (geminiKey) formData.append('gemini_api_key', geminiKey);
    if (teleToken) formData.append('telegram_bot_token', teleToken);
    if (teleChat !== undefined) formData.append('telegram_chat_id', teleChat);
    if (baseUrl) formData.append('base_url', baseUrl);

    const stage_1 = document.getElementById('srs-stage-1')?.value?.trim();
    const stage_2 = document.getElementById('srs-stage-2')?.value?.trim();
    const stage_3 = document.getElementById('srs-stage-3')?.value?.trim();
    const stage_4 = document.getElementById('srs-stage-4')?.value?.trim();
    const stage_5 = document.getElementById('srs-stage-5')?.value?.trim();
    const capStages = document.getElementById('settings-cap-stages')?.checked ?? false;

    // Validate SRS intervals before saving
    const stageVals = [stage_1, stage_2, stage_3, stage_4, stage_5].map(v => (v === undefined || v === null || v === '') ? null : parseInt(v, 10));
    let prevVal = 0;
    for (let idx = 0; idx < stageVals.length; idx++) {
        const val = stageVals[idx];
        if (val !== null) {
            if (isNaN(val) || val < 1 || val > 365) return; // silently skip invalid
            if (val <= prevVal) return;
            prevVal = val;
        }
    }

    if (stage_1) formData.append('stage_1', stage_1);
    if (stage_2) formData.append('stage_2', stage_2);
    if (stage_3) formData.append('stage_3', stage_3);
    if (stage_4) formData.append('stage_4', stage_4);
    if (stage_5) formData.append('stage_5', stage_5);
    formData.append('cap_stages', capStages);

    const repeatStage5 = document.getElementById('settings-repeat-stage-5')?.checked ?? false;
    const stage5RepeatInterval = document.getElementById('srs-stage-5-repeat-interval')?.value?.trim() || '30';
    formData.append('enable_stage_5_repetition', repeatStage5);
    formData.append('stage_5_repeat_interval', stage5RepeatInterval);

    const isNotifEnabled = document.getElementById('settings-notifications-enabled')?.checked ?? true;
    formData.append('notifications_enabled', isNotifEnabled);
    const m1 = parseFloat(document.getElementById('srs-mult-1')?.value);
    const m2 = parseFloat(document.getElementById('srs-mult-2')?.value);
    const m3 = parseFloat(document.getElementById('srs-mult-3')?.value);
    const m4 = parseFloat(document.getElementById('srs-mult-4')?.value);
    const m5 = parseFloat(document.getElementById('srs-mult-5')?.value);

    formData.append('multiplier_1', !isNaN(m1) ? m1 : 4.0);
    formData.append('multiplier_2', !isNaN(m2) ? m2 : 2.5);
    formData.append('multiplier_3', !isNaN(m3) ? m3 : 1.5);
    formData.append('multiplier_4', !isNaN(m4) ? m4 : 1.0);
    formData.append('multiplier_5', !isNaN(m5) ? m5 : 0.7);

    const cap1 = parseInt(document.getElementById('srs-cap-1')?.value) || 2;
    const cap2 = parseInt(document.getElementById('srs-cap-2')?.value) || 3;
    const cap3 = parseInt(document.getElementById('srs-cap-3')?.value) || 4;
    const cap4 = parseInt(document.getElementById('srs-cap-4')?.value) || 5;
    const cap5 = parseInt(document.getElementById('srs-cap-5')?.value) || 5;
    formData.append('cap_1', cap1);
    formData.append('cap_2', cap2);
    formData.append('cap_3', cap3);
    formData.append('cap_4', cap4);
    formData.append('cap_5', cap5);

    const cap15 = (v) => v ? String(Math.min(15, Math.max(1, parseInt(v) || 1))) : '';
    const sc1 = cap15(document.getElementById('star-count-1')?.value.trim());
    const sc2 = cap15(document.getElementById('star-count-2')?.value.trim());
    const sc3 = cap15(document.getElementById('star-count-3')?.value.trim());
    const sc4 = cap15(document.getElementById('star-count-4')?.value.trim());
    const sc5 = cap15(document.getElementById('star-count-5')?.value.trim());
    if (sc1) formData.append('question_count_1', sc1);
    if (sc2) formData.append('question_count_2', sc2);
    if (sc3) formData.append('question_count_3', sc3);
    if (sc4) formData.append('question_count_4', sc4);
    if (sc5) formData.append('question_count_5', sc5);

    formData.append('preferred_hour', document.getElementById('settings-preferred-hour')?.value ?? -1);

    formData.append('notify_telegram', document.getElementById('settings-notify-telegram')?.checked ?? false);
    formData.append('notify_push', document.getElementById('settings-notify-push')?.checked ?? false);
    formData.append('notify_email', document.getElementById('settings-notify-email')?.checked ?? false);
    formData.append('notify_cat_quizzes', document.getElementById('settings-notify-cat-quizzes')?.checked ?? true);
    formData.append('notify_cat_streak', document.getElementById('settings-notify-cat-streak')?.checked ?? true);
    formData.append('notify_cat_inactivity', document.getElementById('settings-notify-cat-inactivity')?.checked ?? true);

    const lbHidden = document.getElementById('leaderboard-hidden-toggle')?.checked ?? false;
    formData.append('leaderboard_hidden', lbHidden);

    const rmSel = document.getElementById('settings-review-mode');
    if (rmSel?.value) formData.append('review_mode', rmSel.value);

    const voiceEngine = localStorage.getItem('studiamo_voice_engine') || 'browser';
    const voiceSpeed = localStorage.getItem('studiamo_voice_speed') || '1.0';
    formData.append('voice_engine', voiceEngine);
    formData.append('voice_speed', voiceSpeed);

    const dnVal = document.getElementById('profile-display-name')?.value.trim();
    if (dnVal) formData.append('display_name', dnVal);

    try {
        await fetchAPI('/api/settings', { method: 'POST', body: formData });
        // Clear sensitive key inputs after save
        const gKey = document.getElementById('settings-gemini-key');
        const tKey = document.getElementById('settings-telegram-token');
        if (gKey && gKey.value) { gKey.value = ''; loadSettings(); }
        if (tKey && tKey.value) { tKey.value = ''; }
        window._userQuestionCounts = null;
        if (typeof initImportanceStars === 'function') initImportanceStars();
        showSettingsIndicator('Saved', 'saved');
    } catch (err) {
        console.error('Autosave failed:', err?.message || err);
        showSettingsIndicator('Save failed', 'failed');
        if (err?.message) {
            showToast(err.message, 'failed');
        }
    }
}

function initSettingsTab() {
    const form = document.getElementById('settings-form');
    if (form) {
        // Prevent default submit (no button anyway)
        form.addEventListener('submit', (e) => e.preventDefault());

        // Autosave on any input change (debounced 1.2s)
        // Guard: only autosave when user is actively interacting (not during loadSettings population)
        form.addEventListener('change', () => { if (!window._settingsLoading) _scheduleSettingsAutosave(); });
        form.addEventListener('input', () => { if (!window._settingsLoading) _scheduleSettingsAutosave(); });
    }

    const dnField = document.getElementById('profile-display-name');
    if (dnField) {
        dnField.addEventListener('change', () => { if (!window._settingsLoading) _scheduleSettingsAutosave(); });
        dnField.addEventListener('input', () => { if (!window._settingsLoading) _scheduleSettingsAutosave(); });
    }

    const starCountInfoToggle = document.getElementById('star-count-info-toggle');
    const starCountInfoBox = document.getElementById('star-count-info-box');
    if (starCountInfoToggle && starCountInfoBox) {
        starCountInfoToggle.addEventListener('click', () => {
            const nowHidden = starCountInfoBox.classList.toggle('hidden');
            starCountInfoToggle.setAttribute('aria-expanded', String(!nowHidden));
        });
    }
}

// Consolidates the three places this modal used to hide itself directly (checkConfig and
// continueAsTestUser in auth.js, the setup form's success handler below) into one place that
// also tells the shared overlay layer, rather than each repeating the same two lines.
function closeSetupWizard() {
    const wizard = document.getElementById('overlay-wizard');
    if (wizard) wizard.classList.add('hidden');
    closeOverlay('overlay-wizard');
}

function initSetupWizard() {
    const wizardBaseUrl = document.getElementById('wizard-base-url');
    if (wizardBaseUrl && (!wizardBaseUrl.value || wizardBaseUrl.value === "http://127.0.0.1:5004")) {
        wizardBaseUrl.value = window.location.origin;
    }
    const wizardForm = document.getElementById('wizard-form');
    if (wizardForm) {
        wizardForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const wizardUser = document.getElementById('wizard-username')?.value.trim();
            const wizardPwd = document.getElementById('wizard-password')?.value.trim();
            const geminiKey = document.getElementById('wizard-gemini-key')?.value.trim();
            const teleToken = document.getElementById('wizard-telegram-token')?.value.trim();
            const baseUrl = document.getElementById('wizard-base-url')?.value;

            if (wizardUser) {
                const userFd = new FormData();
                userFd.append('username', wizardUser);
                if (geminiKey) userFd.append('gemini_api_key', geminiKey);
                if (wizardPwd) userFd.append('password', wizardPwd);

                try {
                    await fetchAPI('/api/users', { method: 'POST', body: userFd });
                    activeUsername = wizardUser;
                    localStorage.setItem('active_username', wizardUser);
                    document.cookie = `username=${wizardUser}; path=/; max-age=31536000`;
                    if (wizardPwd) {
                        sessionStorage.setItem(`profile_password_${wizardUser}`, wizardPwd);
                    }
                } catch (uErr) {
                    console.warn("User profile setup warning:", uErr);
                }
            }

            const formData = new FormData();
            if (geminiKey) formData.append('gemini_api_key', geminiKey);
            if (teleToken) formData.append('telegram_bot_token', teleToken);
            if (baseUrl) formData.append('base_url', baseUrl);


            try {
                await fetchAPI('/api/setup', { method: 'POST', body: formData });
                closeSetupWizard();
                window.location.reload();
            } catch (err) {
                console.error("Setup wizard error:", err);
                if (typeof showToast === 'function') {
                    showToast("Setup error: " + err.message, "failed");
                }
            }
        });
    }
    
    const btnRelaunch = document.getElementById('btn-relaunch-wizard');
    if (btnRelaunch) {
        btnRelaunch.addEventListener('click', async () => {
            const confirmed = await showConfirm({
                title: "Launch Setup Wizard?",
                message: "Are you sure you want to overlay the configuration wizard?",
                confirmText: "Launch Wizard",
                icon: "settings"
            });
            if (confirmed) {
                openOverlay('overlay-wizard', closeSetupWizard);
            }
        });
    }

    // Backup restore was removed: it posted to /api/backup, which has never
    // existed as a route, so the button only ever produced a 404. Export lives
    // on at /api/user/export; re-importing an export is not built yet.
}

function toggleInDepthStats() {
    const el = document.getElementById('indepth-stats-content');
    const chevron = document.getElementById('indepth-stats-chevron');
    if (!el) return;
    if (el.classList.contains('hidden')) {
        el.classList.remove('hidden');
        if (chevron) chevron.classList.add('rotate-180');
    } else {
        el.classList.add('hidden');
        if (chevron) chevron.classList.remove('rotate-180');
    }
}

function toggleApiLogs() {
    const wrapper = document.getElementById('api-logs-wrapper');
    const chevron = document.getElementById('api-logs-chevron');
    if (!wrapper) return;
    if (wrapper.classList.contains('hidden')) {
        wrapper.classList.remove('hidden');
        if (chevron) chevron.classList.add('rotate-180');
    } else {
        wrapper.classList.add('hidden');
        if (chevron) chevron.classList.remove('rotate-180');
    }
}

function toggleAnalyticsSession(sessionId) {
    const el = document.getElementById(`session-details-${sessionId}`);
    const chevron = document.getElementById(`session-chevron-${sessionId}`);
    if (el) {
        if (el.classList.contains('hidden')) {
            el.classList.remove('hidden');
            if (chevron) chevron.classList.add('rotate-180');
            window._expandedSessions[sessionId] = true;
        } else {
            el.classList.add('hidden');
            if (chevron) chevron.classList.remove('rotate-180');
            delete window._expandedSessions[sessionId];
        }
    }
}

function filterAnalyticsHistory() {
    renderAnalyticsHistory();
}

function renderAnalyticsHistory() {
    const container = document.getElementById('analytics-history-container');
    if (!container) return;
    
    const query = (document.getElementById('analytics-search-input')?.value || '').trim().toLowerCase();
    const sortVal = document.getElementById('analytics-sort-select')?.value || 'time-desc';
    
    let filteredAttempts = window._analyticsAttemptsRaw || [];
    if (query) {
        filteredAttempts = filteredAttempts.filter(a => 
            (a.source_title && a.source_title.toLowerCase().includes(query)) ||
            (a.question && a.question.toLowerCase().includes(query)) ||
            (a.given_answer && a.given_answer.toLowerCase().includes(query)) ||
            (a.correct_answer && a.correct_answer.toLowerCase().includes(query))
        );
    }
    
    filteredAttempts.sort((a, b) => new Date(parseDate(b.created_at)) - new Date(parseDate(a.created_at)));
    
    const sessions = [];
    let currentSession = null;
    
    filteredAttempts.forEach(attempt => {
        const time = new Date(parseDate(attempt.created_at));
        if (currentSession && 
            currentSession.quiz_id === attempt.quiz_id && 
            Math.abs(currentSession.lastTime - time) < 20 * 60 * 1000) {
            
            currentSession.attempts.push(attempt);
            currentSession.lastTime = time;
        } else {
            currentSession = {
                id: attempt.id,
                quiz_id: attempt.quiz_id,
                source_title: attempt.source_title,
                srs_stage: attempt.srs_stage,
                lastTime: time,
                created_at: attempt.created_at,
                attempts: [attempt]
            };
            sessions.push(currentSession);
        }
    });
    
    if (sortVal === 'time-desc') {
        sessions.sort((a, b) => new Date(parseDate(b.created_at)) - new Date(parseDate(a.created_at)));
    } else if (sortVal === 'time-asc') {
        sessions.sort((a, b) => new Date(parseDate(a.created_at)) - new Date(parseDate(b.created_at)));
    } else if (sortVal === 'title-asc') {
        sessions.sort((a, b) => (a.source_title || '').localeCompare(b.source_title || ''));
    } else if (sortVal === 'title-desc') {
        sessions.sort((a, b) => (b.source_title || '').localeCompare(a.source_title || ''));
    }
    
    if (sessions.length === 0) {
        container.innerHTML = `<p class="text-xs text-stone-500 text-center py-6">No matching attempts found.</p>`;
        return;
    }
    
    container.innerHTML = '';
    
    sessions.forEach(session => {
        const date = parseDate(session.created_at);
        const localTime = date.toLocaleString();
        const passes = session.attempts.filter(a => a.grade === 'remembered').length;
        const total = session.attempts.length;
        const scorePct = Math.round((passes / total) * 100);
        // -400, not -450: Tailwind's scale has no 450 step, so these three compiled to
        // nothing and every score percentage rendered uncolored. -400 is what the same
        // score badge in videos.js renderVideoStatsAttempts uses, so the two agree.
        const scoreClass = scorePct >= 80 ? 'text-emerald-400' : (scorePct >= 50 ? 'text-amber-400' : 'text-red-400');
        const isExpanded = window._expandedSessions?.[session.id] ? true : false;
        
        let attemptsHTML = '';
        session.attempts.sort((a, b) => a.question_index - b.question_index);
        
        session.attempts.forEach(attempt => {
            const gradeLabel = attempt.grade === 'remembered' ? 'Pass' : 'Fail';
            const gradeBadgeClass = attempt.grade === 'remembered'
                ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                : 'bg-red-500/10 text-red-400 border border-red-500/20';
                
            attemptsHTML += `
                <div class="p-3.5 bg-stone-100 border border-stone-200 rounded-xl space-y-3 shadow-inner">
                    <div class="flex justify-between items-center">
                        <span class="text-[10px] font-bold text-stone-500 uppercase tracking-wider">Question ${attempt.question_index + 1}</span>
                        <span class="text-[9px] font-bold px-2 py-0.5 rounded border uppercase tracking-wider ${gradeBadgeClass}">${gradeLabel}</span>
                    </div>
                    <p class="text-xs text-stone-900 font-semibold leading-relaxed">${attempt.question}</p>
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-2.5 pt-0.5 text-[11px] leading-relaxed">
                        <div>
                            <span class="text-stone-500 block text-[9px] uppercase font-extrabold tracking-wider mb-0.5">Your Guess:</span>
                            <p class="text-stone-700 font-mono bg-stone-50 p-2 rounded-lg border border-stone-200 max-h-[100px] overflow-y-auto whitespace-pre-wrap">${attempt.given_answer || '<span class="text-stone-400 italic">No guess provided / flipped</span>'}</p>
                        </div>
                        <div>
                            <span class="text-emerald-500 block text-[9px] uppercase font-extrabold tracking-wider mb-0.5">AI Correct Answer:</span>
                            <p class="text-emerald-455 font-mono bg-stone-50 p-2 rounded-lg border border-stone-200 max-h-[100px] overflow-y-auto whitespace-pre-wrap">${attempt.correct_answer}</p>
                        </div>
                    </div>
                </div>
            `;
        });
        
        container.innerHTML += `
            <div class="bg-stone-100 border border-stone-200 rounded-xl overflow-hidden shadow-sm">
                <button type="button" onclick="toggleAnalyticsSession(${session.id})" class="w-full p-3.5 flex justify-between items-center text-left hover:bg-stone-100 transition focus:outline-none">
                    <div class="min-w-0 flex-grow pr-3 space-y-1">
                        <div class="flex flex-wrap items-center gap-1.5">
                            <span class="text-[9px] bg-amber-500/10 border border-amber-200 text-amber-700 px-1.5 py-0.5 rounded font-bold uppercase tracking-wider">Stage ${session.srs_stage}</span>
                            <span class="text-[9px] bg-stone-100 text-stone-500 px-1.5 py-0.5 rounded font-bold uppercase tracking-wider">${total} Qs</span>
                            <span class="text-[10px] text-stone-500 font-medium">${localTime}</span>
                        </div>
                        <h5 class="text-xs font-bold text-stone-900 truncate" title="${session.source_title}">${session.source_title}</h5>
                    </div>
                    <div class="flex items-center space-x-3 shrink-0">
                        <span class="text-xs font-extrabold ${scoreClass}">${scorePct}% Correct</span>
                        <i data-lucide="chevron-down" id="session-chevron-${session.id}" class="w-4 h-4 text-stone-400 transition-transform ${isExpanded ? 'rotate-180' : ''}"></i>
                    </div>
                </button>
                
                <div id="session-details-${session.id}" class="${isExpanded ? '' : 'hidden'} p-3.5 bg-stone-100 border-t border-stone-200 space-y-3">
                    ${attemptsHTML}
                </div>
            </div>
        `;
    });
}

// Theme switching removed : Warm Paper Sepia is the permanent design.

function setVoiceEngine(engine) {
    const validEngine = engine === 'gemini' ? 'gemini' : 'browser';
    localStorage.setItem('studiamo_voice_engine', validEngine);

    // Update pill-toggle active state. Only .is-active moves: the buttons keep their
    // .segmented-tab styling and padding from the template, which reassigning .className
    // used to throw away and replace with a second copy maintained here.
    const btnBrowser = document.getElementById('voice-card-browser');
    const btnGemini = document.getElementById('voice-card-gemini');
    if (btnBrowser) btnBrowser.classList.toggle('is-active', validEngine === 'browser');
    if (btnGemini) btnGemini.classList.toggle('is-active', validEngine === 'gemini');
    if (!window._settingsLoading && typeof _submitSettings === 'function') {
        _submitSettings(true);
    }
}

function updateVoiceSpeedDisplay(val) {
    const speed = parseFloat(val).toFixed(2);
    const display = document.getElementById('voice-speed-display');
    if (display) display.textContent = `${speed}x`;
}

function setVoiceSpeed(val) {
    const speed = parseFloat(val).toFixed(2);
    localStorage.setItem('studiamo_voice_speed', speed);
    if (!window._settingsLoading && typeof _scheduleSettingsAutosave === 'function') {
        _scheduleSettingsAutosave();
    }
}

function initVoiceSettings() {
    const savedEngine = localStorage.getItem('studiamo_voice_engine') || 'browser';
    const savedSpeed = parseFloat(localStorage.getItem('studiamo_voice_speed') || '1.0');

    // Restore toggle state
    setVoiceEngine(savedEngine);

    // Restore speed slider
    const slider = document.getElementById('voice-speed-slider');
    if (slider) slider.value = savedSpeed;
    updateVoiceSpeedDisplay(savedSpeed);
}

let _voiceTestSession = null; // { btn, mode: 'speech'|'audio', audio, paused }

function _finishVoiceTest(btn, origContent) {
    if (btn) {
        btn.innerHTML = origContent;
        btn.disabled = false;
        btn.classList.remove('opacity-75', 'cursor-wait');
        if (typeof renderIcons === 'function') renderIcons();
    }
    if (_voiceTestSession && _voiceTestSession.btn === btn) {
        _voiceTestSession = null;
    }
}

function _showVoiceTestPlaying(btn, paused) {
    btn.innerHTML = paused
        ? `<i data-lucide="play-circle" class="w-3.5 h-3.5 text-amber-700"></i><span>Resume Sample</span>`
        : `<i data-lucide="pause-circle" class="w-3.5 h-3.5 text-amber-700"></i><span>Pause Sample</span>`;
    btn.disabled = false;
    btn.classList.remove('opacity-75', 'cursor-wait');
    if (typeof renderIcons === 'function') renderIcons();
}

async function testVoiceSample(btn) {
    if (!btn) return;

    // Sample already running on this button: toggle pause/resume instead of restarting.
    if (_voiceTestSession && _voiceTestSession.btn === btn) {
        const session = _voiceTestSession;
        if (session.mode === 'speech') {
            if (session.paused) {
                window.speechSynthesis.resume();
            } else {
                window.speechSynthesis.pause();
            }
        } else if (session.audio) {
            if (session.audio.paused) {
                session.audio.play();
            } else {
                session.audio.pause();
            }
        }
        session.paused = !session.paused;
        _showVoiceTestPlaying(btn, session.paused);
        return;
    }

    const engine = localStorage.getItem('studiamo_voice_engine') || 'browser';
    const speed = parseFloat(localStorage.getItem('studiamo_voice_speed') || '1.0');
    const text = "Welcome to Studiamo. Active recall is the fastest way to master new knowledge.";
    const origContent = btn.innerHTML;

    const icon = btn.querySelector('i, svg');
    if (icon) {
        icon.outerHTML = `<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin shrink-0"></i>`;
    }
    btn.disabled = true;
    btn.classList.add('opacity-75', 'cursor-wait');
    if (typeof renderIcons === 'function') renderIcons();

    const speakInBrowser = () => {
        if (!('speechSynthesis' in window)) throw new Error('Browser speech synthesis unavailable.');
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = speed;
        utterance.lang = 'en-US';
        const voices = window.speechSynthesis.getVoices();
        const preferredVoice = voices.find(v => v.lang === 'en-US' && /male|guy|david|mark|alex/i.test(v.name))
            || voices.find(v => v.lang === 'en-US')
            || voices.find(v => v.lang.startsWith('en'));
        if (preferredVoice) utterance.voice = preferredVoice;
        utterance.onend = () => _finishVoiceTest(btn, origContent);
        utterance.onerror = () => _finishVoiceTest(btn, origContent);
        _voiceTestSession = { btn, mode: 'speech', paused: false };
        window.speechSynthesis.speak(utterance);
        _showVoiceTestPlaying(btn, false);
    };

    try {
        if (engine === 'browser') {
            speakInBrowser();
        } else {
            const fd = new FormData();
            fd.append('text', text);
            fd.append('speed', speed);
            const res = await fetchAPI('/api/tts', { method: 'POST', body: fd });
            const audioSrc = res && (res.audio_data || res.audio_url);
            if (!audioSrc) throw new Error('No audio data returned from server.');
            const audio = new Audio(audioSrc);
            audio.onended = () => _finishVoiceTest(btn, origContent);
            audio.onerror = () => _finishVoiceTest(btn, origContent);
            _voiceTestSession = { btn, mode: 'audio', audio, paused: false };
            await audio.play();
            _showVoiceTestPlaying(btn, false);
        }
    } catch (e) {
        console.warn('Edge TTS sample failed, falling back to browser voice:', e);
        _voiceTestSession = null;
        if (engine !== 'browser') {
            try {
                speakInBrowser();
                return;
            } catch (fallbackErr) {
                console.error('Browser voice fallback also failed:', fallbackErr);
            }
        }
        _finishVoiceTest(btn, origContent);
        if (typeof showToast === 'function') {
            showToast('Could not play voice sample', 'failed');
        } else {
            alert('Could not play voice sample: ' + e.message);
        }
    }
}

async function testTelegramNotification() {
    const btn = document.getElementById('btn-test-telegram');
    let origContent = '';
    if (btn) {
        origContent = btn.innerHTML;
        const icon = btn.querySelector('i, svg');
        if (icon) {
            icon.outerHTML = `<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin shrink-0"></i>`;
        }
        btn.disabled = true;
        btn.classList.add('opacity-75', 'cursor-wait');
        if (typeof renderIcons === 'function') renderIcons();
    }
    try {
        const res = await fetchAPI('/api/settings/test-notification', { method: 'POST' });
        showToast("Telegram test message sent!", "saved");
    } catch (e) {
        console.error("Test notification failed:", e);
        showToast("Test notification failed: " + (e.detail || e.message), "failed");
    } finally {
        if (btn) {
            btn.innerHTML = origContent;
            btn.disabled = false;
            btn.classList.remove('opacity-75', 'cursor-wait');
            if (typeof renderIcons === 'function') renderIcons();
        }
    }
}

let _onboardingStatusCache = null;

async function checkOnboardingAndUpdates() {
    try {
        const data = await fetchAPI('/api/user/onboarding_status');
        _onboardingStatusCache = data;
        
        if (!data.has_seen_onboarding) {
            openTabGuideModal();
        } else if (!data.has_seen_updates) {
            openUpdatesModal();
        }
    } catch (e) {
        console.warn("Failed to check onboarding/updates status:", e);
    }
}

function openTabGuideModal(e) {
    if (e && typeof e.preventDefault === 'function') e.preventDefault();
    const el = document.getElementById('overlay-tab-guide');
    if (el) {
        openOverlay('overlay-tab-guide', closeTabGuideModal);
        if (typeof renderIcons === 'function') renderIcons();
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
}

function closeTabGuideModal(e) {
    if (e && typeof e.preventDefault === 'function') e.preventDefault();
    const el = document.getElementById('overlay-tab-guide');
    if (el) {
        el.classList.add('hidden');
        closeOverlay('overlay-tab-guide');
    }
}

async function dismissTabGuide(e) {
    closeTabGuideModal(e);
    try {
        const fd = new FormData();
        fd.append('has_seen_onboarding', 'true');
        await fetchAPI('/api/user/onboarding_status', { method: 'POST', body: fd });
        
        if (_onboardingStatusCache && !_onboardingStatusCache.has_seen_updates) {
            openUpdatesModal();
        }
    } catch (err) {
        console.error("Failed to dismiss tab guide:", err);
    }
}

function openUpdatesModal(e) {
    if (e && typeof e.preventDefault === 'function') e.preventDefault();
    const el = document.getElementById('overlay-updates-modal');
    if (el) {
        openOverlay('overlay-updates-modal', closeUpdatesModal);
        if (typeof renderIcons === 'function') renderIcons();
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
}

function closeUpdatesModal(e) {
    if (e && typeof e.preventDefault === 'function') e.preventDefault();
    const el = document.getElementById('overlay-updates-modal');
    if (el) {
        el.classList.add('hidden');
        closeOverlay('overlay-updates-modal');
    }
}

async function dismissUpdates(e) {
    closeUpdatesModal(e);
    try {
        const fd = new FormData();
        fd.append('has_seen_updates', 'true');
        await fetchAPI('/api/user/onboarding_status', { method: 'POST', body: fd });
    } catch (err) {
        console.error("Failed to dismiss updates modal:", err);
    }
}

// Window bindings for inline HTML attribute calls
window.loadStats = loadStats;
window.checkOnboardingAndUpdates = checkOnboardingAndUpdates;
window.openTabGuideModal = openTabGuideModal;
window.closeTabGuideModal = closeTabGuideModal;
window.dismissTabGuide = dismissTabGuide;
window.openUpdatesModal = openUpdatesModal;
window.closeUpdatesModal = closeUpdatesModal;
window.dismissUpdates = dismissUpdates;
window.loadSettings = loadSettings;
window.toggleCapStagesPanel = toggleCapStagesPanel;
window.togglePwdVisibility = togglePwdVisibility;
window.handleProfileSave = handleProfileSave;
window.initSettingsTab = initSettingsTab;
window.setLeaderboardHidden = setLeaderboardHidden;
window.initSetupWizard = initSetupWizard;
window.toggleInDepthStats = toggleInDepthStats;
window.toggleApiLogs = toggleApiLogs;
window.toggleAnalyticsSession = toggleAnalyticsSession;
window.filterAnalyticsHistory = filterAnalyticsHistory;
window.renderAnalyticsHistory = renderAnalyticsHistory;
window.setVoiceEngine = setVoiceEngine;
window.updateVoiceSpeedDisplay = updateVoiceSpeedDisplay;
window.setVoiceSpeed = setVoiceSpeed;
window.initVoiceSettings = initVoiceSettings;
window.testVoiceSample = testVoiceSample;
window.showToast = showToast;
window.hideToast = hideToast;
window.showConfirm = showConfirm;
window.showPrompt = showPrompt;
window.showSettingsIndicator = showSettingsIndicator;
window.testTelegramNotification = testTelegramNotification;

// --- PWA & Notification Channel Helpers ---

function toggleTelegramNotifyPanel(enabled) {
    const panel = document.getElementById('telegram-notify-content');
    if (panel) panel.classList.toggle('hidden', !enabled);
    if (enabled && 'Notification' in window === false) {
        // no-op: browser support unrelated to Telegram, kept for clarity
    }
}

function togglePushNotifyPanel(enabled) {
    const panel = document.getElementById('push-notify-content');
    if (panel) panel.classList.toggle('hidden', !enabled);
    if (enabled && 'Notification' in window && Notification.permission === 'default') {
        requestBrowserNotificationPermission();
    }
}

function toggleEmailNotifyPanel(enabled) {
    const panel = document.getElementById('email-notify-content');
    if (panel) panel.classList.toggle('hidden', !enabled);
}

function updateTelegramConnectStatus(configData) {
    const statusEl = document.getElementById('telegram-connect-status');
    const testBtn = document.getElementById('btn-test-telegram-managed');
    const connectBtn = document.getElementById('btn-connect-telegram');
    const connected = !!(configData && configData.telegram_chat_id);
    if (statusEl) {
        statusEl.textContent = connected ? 'Connected' : 'Not connected yet';
        statusEl.className = connected ? 'text-emerald-700 font-semibold' : 'text-stone-600';
    }
    if (testBtn) testBtn.classList.toggle('hidden', !connected);
    if (connectBtn) connectBtn.textContent = connected ? 'Reconnect Telegram' : 'Connect Telegram';
}

let _telegramConnectPollTimer = null;

async function connectTelegram() {
    const btn = document.getElementById('btn-connect-telegram');
    // Open the tab synchronously, in direct response to the click , browsers
    // (especially Safari/mobile) silently block window.open() called after
    // an await, since the async gap breaks the "direct user gesture" chain.
    const newTab = window.open('', '_blank');
    try {
        const res = await fetchAPI('/api/settings/telegram/connect-link');
        if (!res || !res.url) throw new Error('No connect link returned');
        if (newTab) {
            newTab.location.href = res.url;
        } else {
            // Even the synchronous open was blocked , fall back to a same-tab redirect.
            window.location.href = res.url;
            return;
        }
    } catch (e) {
        if (newTab) newTab.close();
        console.error('Telegram connect-link error:', e);
        showToast('Could not start Telegram connect: ' + (e.detail || e.message), 'failed');
        return;
    }

    if (btn) { btn.disabled = true; btn.textContent = 'Waiting for confirmation...'; }
    if (_telegramConnectPollTimer) clearInterval(_telegramConnectPollTimer);

    let attempts = 0;
    _telegramConnectPollTimer = setInterval(async () => {
        attempts++;
        try {
            const configData = await fetchAPI('/api/settings');
            if (configData && configData.telegram_chat_id) {
                clearInterval(_telegramConnectPollTimer);
                window._lastSettingsConfig = configData;
                updateTelegramConnectStatus(configData);
                if (btn) { btn.disabled = false; btn.textContent = 'Reconnect Telegram'; }
                showToast('Telegram connected!', 'saved');
                return;
            }
        } catch (e) {
            console.warn('Telegram connect poll error:', e);
        }
        if (attempts >= 20) {
            clearInterval(_telegramConnectPollTimer);
            if (btn) { btn.disabled = false; btn.textContent = 'Connect Telegram'; }
        }
    }, 3000);
}

async function testPushNotification() {
    const btn = document.getElementById('btn-test-push');
    if (btn) { btn.disabled = true; btn.classList.add('opacity-75', 'cursor-wait'); }
    try {
        await fetchAPI('/api/settings/test-push', { method: 'POST' });
        showToast('Test push sent!', 'saved');
    } catch (e) {
        console.error('Test push failed:', e);
        showToast('Test push failed: ' + (e.detail || e.message), 'failed');
    } finally {
        if (btn) { btn.disabled = false; btn.classList.remove('opacity-75', 'cursor-wait'); }
    }
}

async function testEmailNotification() {
    const btn = document.getElementById('btn-test-email');
    if (btn) { btn.disabled = true; btn.classList.add('opacity-75', 'cursor-wait'); }
    try {
        await fetchAPI('/api/settings/test-email', { method: 'POST' });
        showToast('Test email sent!', 'saved');
    } catch (e) {
        console.error('Test email failed:', e);
        showToast('Test email failed: ' + (e.detail || e.message), 'failed');
    } finally {
        if (btn) { btn.disabled = false; btn.classList.remove('opacity-75', 'cursor-wait'); }
    }
}

window.toggleTelegramNotifyPanel = toggleTelegramNotifyPanel;
window.togglePushNotifyPanel = togglePushNotifyPanel;
window.toggleEmailNotifyPanel = toggleEmailNotifyPanel;
window.connectTelegram = connectTelegram;
window.testPushNotification = testPushNotification;
window.testEmailNotification = testEmailNotification;

function updateBrowserNotificationStatus() {
    const statusEl = document.getElementById('browser-notif-status');
    if (!statusEl) return;
    if (!('Notification' in window)) {
        statusEl.textContent = 'Not supported';
        statusEl.className = 'text-[10px] px-2 py-0.5 rounded-full font-mono bg-red-950/80 text-red-400 border border-red-800';
    } else if (Notification.permission === 'granted') {
        statusEl.textContent = 'Enabled (Allowed)';
        statusEl.className = 'text-[10px] px-2 py-0.5 rounded-full font-mono bg-emerald-950/80 text-emerald-400 border border-emerald-800';
        subscribeWebPush();
    } else if (Notification.permission === 'denied') {
        statusEl.textContent = 'Blocked';
        statusEl.className = 'text-[10px] px-2 py-0.5 rounded-full font-mono bg-amber-950/80 text-amber-400 border border-amber-800';
    } else {
        statusEl.textContent = 'Not requested';
        statusEl.className = 'text-[10px] px-2 py-0.5 rounded-full font-mono bg-stone-100 text-stone-500';
    }
}

function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding).replace(/\-/g, '+').replace(/_/g, '/');
    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; ++i) {
        outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
}

async function subscribeWebPush() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) return;
    try {
        const reg = await navigator.serviceWorker.ready;
        const res = await fetchAPI('/api/push/vapid_public_key');
        if (!res || !res.public_key) return;

        const convertedVapidKey = urlBase64ToUint8Array(res.public_key);
        let sub = await reg.pushManager.getSubscription();
        if (!sub) {
            sub = await reg.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: convertedVapidKey
            });
        }

        await fetchAPI('/api/push/subscribe', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(sub)
        });
    } catch (err) {
        console.warn('Web Push subscription registration error:', err);
    }
}

async function requestBrowserNotificationPermission() {
    if (!('Notification' in window)) {
        alert('Browser notifications are not supported by this browser.');
        return;
    }
    try {
        const perm = await Notification.requestPermission();
        updateBrowserNotificationStatus();
        if (perm === 'granted') {
            await subscribeWebPush();
            new Notification('Studiamo Recall', {
                body: 'Web notifications & PWA push are now active!',
                icon: '/static/images/icon-192.png'
            });
        }
    } catch (e) {
        console.error('Notification permission error:', e);
    }
}

let deferredPWAInstallPrompt = null;

window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPWAInstallPrompt = e;
    const btn = document.getElementById('pwa-install-btn');
    if (btn) btn.classList.remove('hidden');
});

window.addEventListener('appinstalled', () => {
    deferredPWAInstallPrompt = null;
});

function triggerPWAInstall() {
    if (deferredPWAInstallPrompt) {
        deferredPWAInstallPrompt.prompt();
        deferredPWAInstallPrompt.userChoice.then((choice) => {
            deferredPWAInstallPrompt = null;
        });
    } else {
        const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
        const iosBox = document.getElementById('pwa-ios-instructions');
        if (iosBox) iosBox.classList.toggle('hidden');
        if (!isIOS) {
            alert('To install Studiamo as an app, use the "Add to Home Screen" or "Install App" option in your browser menu.');
        }
    }
}

// Service Worker Registration
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js').then((reg) => {
            console.log('[PWA] Service Worker registered with scope:', reg.scope);
        }).catch((err) => {
            console.warn('[PWA] Service Worker registration failed:', err);
        });
    });
}

function getStoredNotifiedIds() {
    try {
        const stored = localStorage.getItem('studiamo_notified_quiz_ids');
        return stored ? new Set(JSON.parse(stored)) : new Set();
    } catch (e) {
        return new Set();
    }
}

function saveStoredNotifiedIds(setObj) {
    try {
        localStorage.setItem('studiamo_notified_quiz_ids', JSON.stringify(Array.from(setObj)));
        localStorage.setItem('studiamo_last_notif_time', Date.now().toString());
    } catch (e) {}
}

async function checkAppDueNotifications() {
    if (!window._lastSettingsConfig || !window._lastSettingsConfig.notify_push) return;
    if (!('Notification' in window) || Notification.permission !== 'granted') return;

    const lastNotifTime = parseInt(localStorage.getItem('studiamo_last_notif_time') || '0');
    const now = Date.now();
    const storedSet = getStoredNotifiedIds();

    try {
        // --- Streak Warning Web Push Check ---
        if (window.currentUserStats && currentUserStats.streak > 0 && currentUserStats.last_quiz_at) {
            const lastDate = typeof parseDate === 'function' ? parseDate(currentUserStats.last_quiz_at) : new Date(currentUserStats.last_quiz_at);
            if (lastDate && !isNaN(lastDate.getTime())) {
                const expireTime = lastDate.getTime() + (24 * 60 * 60 * 1000);
                const msLeft = expireTime - now;
                const hoursLeft = msLeft / (1000 * 60 * 60);

                const todayStr = new Date().toISOString().split('T')[0];
                const lastStreakWarnDate = localStorage.getItem('studiamo_streak_warned_date');

                if (hoursLeft > 0 && hoursLeft <= 5 && lastStreakWarnDate !== todayStr) {
                    localStorage.setItem('studiamo_streak_warned_date', todayStr);
                    const h = Math.ceil(hoursLeft);
                    const streakTitle = `🔥 Streak at risk (${currentUserStats.streak} days)!`;
                    const streakBody = `Your streak expires in ~${h} hour(s). Complete 1 quick review now!`;

                    if (navigator.serviceWorker && navigator.serviceWorker.controller) {
                        navigator.serviceWorker.ready.then(reg => {
                            reg.showNotification(streakTitle, {
                                body: streakBody,
                                icon: '/static/images/icon-192.png',
                                badge: '/static/images/icon-192.png',
                                data: { url: '/#review-section' }
                            });
                        });
                    } else {
                        new Notification(streakTitle, {
                            body: streakBody,
                            icon: '/static/images/icon-192.png'
                        });
                    }
                }
            }
        }

        const res = await fetchAPI('/api/notifications/due');
        if (res && res.due_count > 0) {
            const unnotifiedItems = res.items.filter(item => !storedSet.has(item.id));

            // Only notify if there are new unnotified items OR 4+ hours have passed
            if (unnotifiedItems.length > 0 || (now - lastNotifTime > 4 * 60 * 60 * 1000)) {
                res.items.forEach(item => storedSet.add(item.id));
                saveStoredNotifiedIds(storedSet);

                const countToReport = unnotifiedItems.length > 0 ? unnotifiedItems.length : res.due_count;
                const title = `🧠 ${countToReport} review(s) due!`;
                const body = countToReport === 1 && unnotifiedItems.length === 1
                    ? `Reminder: "${unnotifiedItems[0].title}" is ready now.`
                    : `You have ${res.due_count} reviews due in Studiamo.`;

                if (navigator.serviceWorker && navigator.serviceWorker.controller) {
                    navigator.serviceWorker.ready.then(reg => {
                        reg.showNotification(title, {
                            body: body,
                            icon: '/static/images/icon-192.png',
                            badge: '/static/images/icon-192.png',
                            data: { url: '/#review-section' }
                        });
                    });
                } else {
                    new Notification(title, {
                        body: body,
                        icon: '/static/images/icon-192.png'
                    });
                }
            }
        } else {
            localStorage.removeItem('studiamo_notified_quiz_ids');
        }
    } catch (e) {
        console.warn('App notification check error:', e);
    }
}

function toggleNotificationsMasterSwitch(enabled) {
    const label = document.getElementById('notifications-enabled-label');
    const panel = document.getElementById('notifications-panel-content');
    if (label) {
        label.textContent = enabled ? 'Enabled' : 'Disabled';
        label.className = enabled ? 'ml-2 text-xs font-semibold text-emerald-600' : 'ml-2 text-xs font-semibold text-stone-500';
    }
    if (panel) {
        panel.classList.toggle('hidden', !enabled);
    }
}

setInterval(checkAppDueNotifications, 5 * 60 * 1000);
setTimeout(checkAppDueNotifications, 5000);

if ('Notification' in window && Notification.permission === 'granted') {
    setTimeout(subscribeWebPush, 2000);
}

window.requestBrowserNotificationPermission = requestBrowserNotificationPermission;
window.triggerPWAInstall = triggerPWAInstall;
window.toggleNotificationsMasterSwitch = toggleNotificationsMasterSwitch;
window.subscribeWebPush = subscribeWebPush;
window.toggleStage5RepeatPanel = toggleStage5RepeatPanel;
window.toggleSrsConfigPanel = toggleSrsConfigPanel;







// --- Account Deletion (two-step confirmation) --------------------------------
// Step 1 offers a data export and can be cancelled; step 2 states that deletion
// is permanent and requires the username to be typed back before the button
// enables. Nothing is sent to the server until that final click.

function openDeleteAccountStep1() {
    const note = document.getElementById('delete-account-export-note');
    if (note) {
        note.classList.add('hidden');
        note.classList.remove('flex');
    }
    openOverlay('overlay-delete-account-step1', closeDeleteAccountModals);
    if (typeof renderIcons === 'function') renderIcons();
}

function markExportDownloaded() {
    // The browser handles the download itself; this only confirms it started so
    // the user isn't left guessing whether the click registered.
    const note = document.getElementById('delete-account-export-note');
    if (note) {
        note.classList.remove('hidden');
        note.classList.add('flex');
        if (typeof renderIcons === 'function') renderIcons();
    }
}

function openDeleteAccountStep2() {
    document.getElementById('overlay-delete-account-step1')?.classList.add('hidden');
    closeOverlay('overlay-delete-account-step1');

    const hint = document.getElementById('delete-account-username-hint');
    if (hint) hint.textContent = activeUsername || 'your username';

    const input = document.getElementById('delete-account-confirm-input');
    if (input) {
        input.value = '';
        input.placeholder = activeUsername || 'Your username';
    }
    validateDeleteAccountConfirm();

    openOverlay('overlay-delete-account-step2', closeDeleteAccountModals);
    if (typeof renderIcons === 'function') renderIcons();
    setTimeout(() => input?.focus(), 50);
}

function closeDeleteAccountModals() {
    document.getElementById('overlay-delete-account-step1')?.classList.add('hidden');
    document.getElementById('overlay-delete-account-step2')?.classList.add('hidden');
    closeOverlay('overlay-delete-account-step1');
    closeOverlay('overlay-delete-account-step2');
    const input = document.getElementById('delete-account-confirm-input');
    if (input) input.value = '';
    validateDeleteAccountConfirm();
}

function validateDeleteAccountConfirm() {
    const input = document.getElementById('delete-account-confirm-input');
    const btn = document.getElementById('btn-confirm-delete-account');
    if (!btn) return;

    const typed = (input?.value || '').trim().toLowerCase();
    const matches = typed && typed === (activeUsername || '').toLowerCase();

    btn.disabled = !matches;
    btn.className = matches
        ? 'flex-1 py-2.5 px-4 bg-red-600 hover:bg-red-700 border border-red-600 text-white font-bold rounded-xl text-xs transition'
        : 'flex-1 py-2.5 px-4 bg-stone-100 border border-stone-200 text-stone-400 font-bold rounded-xl text-xs transition cursor-not-allowed';
}

async function confirmDeleteAccount() {
    const input = document.getElementById('delete-account-confirm-input');
    const btn = document.getElementById('btn-confirm-delete-account');
    const typed = (input?.value || '').trim();
    if (!typed || typed.toLowerCase() !== (activeUsername || '').toLowerCase()) return;

    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Deleting…';
        btn.className = 'flex-1 py-2.5 px-4 bg-red-600 text-white font-bold rounded-xl text-xs opacity-75 cursor-wait';
    }

    const fd = new FormData();
    fd.append('confirm_username', typed);

    try {
        await fetchAPI('/api/user/delete', { method: 'POST', body: fd });
    } catch (e) {
        if (btn) {
            btn.textContent = 'Permanently Delete';
            validateDeleteAccountConfirm();
        }
        showToast('Could not delete account', 'failed');
        return;
    }

    // The account and its session are gone server-side. Clear local traces and
    // leave the app rather than letting the next request 401 on a dead session.
    localStorage.removeItem('active_username');
    sessionStorage.removeItem('profile_password');
    document.cookie = 'username=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
    document.cookie = 'profile_password=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
    window.location.href = '/login?deleted=1';
}

window.openDeleteAccountStep1 = openDeleteAccountStep1;
window.markExportDownloaded = markExportDownloaded;
window.openDeleteAccountStep2 = openDeleteAccountStep2;
window.closeDeleteAccountModals = closeDeleteAccountModals;
window.validateDeleteAccountConfirm = validateDeleteAccountConfirm;
window.confirmDeleteAccount = confirmDeleteAccount;

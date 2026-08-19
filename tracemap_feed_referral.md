# Trace Map: Feed, Prompts, Referrals

## 1. Feed and prompt entrypoints

### Telegram

- `menu_feed`
- `menu_prompts`
- publish/share/remix/repeat callbacks
- partner/referral menus

### Mini App

- `POST /mini-app/api/feed`
- `POST /mini-app/api/feed/item`
- `POST /mini-app/api/feed/my`
- `GET|POST /mini-app/api/feed/profile`
- `POST /mini-app/api/feed/like`
- `POST /mini-app/api/feed/share`
- `GET|POST /mini-app/api/feed/comments`
- `POST /mini-app/api/feed/comment`
- `POST /mini-app/api/feed/remove`
- `POST /mini-app/api/feed/remix`
- `POST /mini-app/api/prompts*`
- `POST /mini-app/api/profile/channel`

## 2. Feed publish flow

`completed generation`
-> user chooses `Лента и профиль` or `Только профиль`
-> `Лента и профиль`: safe publication is visible on both surfaces
-> `Только профиль`: publication never enters the general feed
-> content marked `18+` is forced to `Только профиль` and blur
-> profile-only likes/comments/shares/remix are available from the author profile; the general feed still never lists the publication

## 3. Prompt library flow

`user submits prompt`
-> validation
-> `user_prompts` row created
-> moderation status applied
-> prompt can later be liked, linked, reused, deactivated

Prompt-related counters/events:

- `prompt_likes`
- `prompt_repeat_events`
- author stats

## 4. Remix / repeat flow

### Remix

`feed item`
-> remix action
-> source generation id preserved
-> new generation launches with inherited context
-> feed_remix event recorded

### Repeat

`prompt/generation reuse`
-> source prompt/generation referenced
-> repeat balance/partner side effects may apply
-> prompt_repeat event stored

## 5. Referral and deep-link flow

### Link construction

`bot/miniapp_links.py` builds:

- referral links
- profile links
- feed links
- remix links
- prompt links
- task links

### Referral entry

`/start ref_CODE` or `?startapp=ref_CODE`
-> referral code parsed
-> user binding / attribution saved
-> referral anti-fraud checks hourly, daily and burst thresholds
-> suspicious burst may emit `referral_events.reason = burst_autoban`
-> admin partner screen `Burst autobans` shows latest incidents
-> later successful payment may trigger referral revenue path

## 6. Profile/channel flow

Mini App profile endpoints allow:

- reading public profile feed
- saving user channel URL
- sharing public profile links

## 7. Main tables

- `generation_tasks`
- `user_prompts`
- `prompt_likes`
- `feed_generation_likes`
- `feed_comments`
- `feed_remix_events`
- `prompt_repeat_events`
- `referrals`
- `users`

## 8. Important checks

- user can only mutate own publication state where required
- hidden prompt/remix tasks should not leak as reusable originals
- public profile/feed lookups must stay scoped and safe
- referral code parsing must not overwrite existing trusted linkage

## ADR-018: Self-hosted Web Push via VAPID + `web-push` over third-party push services

**Status:** Accepted
**Date:** 2026-04-12 [Session 15]

**Context**
The conventional choices for push notifications are OneSignal, Firebase Cloud Messaging, or one of several smaller vendors. They handle delivery, retries, segmentation, and analytics. The cost is per-message pricing, vendor lock-in, and routing every notification’s content through a third party. For a club management app with thirty members, the volume is low enough that vendor pricing is not a primary concern; the question is whether vendor convenience outweighs vendor risk.

**Decision**
Push delivery is self-hosted. VAPID keys generated locally via `scripts/generate-vapid-keys.js` (depends on `web-push`). Two environment variables: `NEXT_PUBLIC_VAPID_PUBLIC_KEY` (browser, exposed) and `VAPID_PRIVATE_KEY` (server, secret). Delivery via the `web-push` npm package running on Vercel functions. No third-party service in the data path.

**Consequences**

- **No per-message cost.** The venue’s push volume could grow 100× before infrastructure cost would become noticeable. At the current scale, push delivery is effectively free.
- **No vendor lock-in.** Swapping `web-push` for another VAPID implementation is mechanical. The subscription endpoints stored in the database are standard; no proprietary identifiers.
- **No privacy delegation.** Notification payloads never leave the application’s infrastructure. For a venue handling member data, this is a regulatory non-issue but an ergonomic positive — there’s nothing to add to a privacy policy regarding third-party push.
- **Negative: delivery monitoring is on us.** There’s no vendor dashboard showing “you sent N pushes; X% delivered, Y% clicked.” Failures are logged and 404/410 cleanup is automatic, but anything richer (delivery analytics, per-user retry policies, A/B testing) is build-it-ourselves.
- **Negative: subscription cleanup is the application’s responsibility.** Dead subscriptions stay in `push_subscriptions` until a delivery attempt 410s and the cleanup path runs. A vendor would garbage-collect for us. In practice the cleanup is mechanical (the `web-push` library returns 410 cleanly) but it’s our code, not their problem.
- **Negative: segmentation, scheduling, and A/B testing are out of scope.** The current pipeline does “deliver this payload to this user, fire-and-forget”; anything else would have to be built. For the venue use case, this is fine. For a different scale or use case, the build-it-ourselves cost would dominate.
- **Negative: VAPID key rotation invalidates every active subscription.** Rotating either key requires every client to re-enable push from `/profile`. There’s no graceful migration. For now this is an accepted operational constraint.

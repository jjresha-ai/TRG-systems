# Basic / Table-Stakes CRM Features

Scope: the baseline feature set any CRM must cover before differentiators matter, with a CRE brokerage / investment-sales lens.

Method note: compiled from working knowledge of the named products' public documentation and feature sets (Salesforce, HubSpot, Pipedrive, Zoho, Follow Up Boss, Apto, Buildout, plus others where relevant). Live web verification was not performed in this pass, so vendor-specific claims (tiers, limits, pricing) should be re-checked before being used in a buy/build decision.

Vendor shorthand: SF = Salesforce, HS = HubSpot, PD = Pipedrive, ZO = Zoho CRM, FUB = Follow Up Boss (residential-agent focus), Apto = CRE brokerage CRM (built on Salesforce), Buildout = CRE listing/marketing/deal platform with CRM, plus CRE-native tools noted inline (Juniper Square for investor relations, Altus/ARGUS not CRM).

---

## 1. Contact and Account Management

**What it is:** A system of record for people (contacts) and the organizations they belong to (accounts/companies), with relationships between them, ownership (which user owns the relationship), and a unified timeline of all interactions.

**Why it matters:** It is the foundation; every other feature hangs off it. Duplicate or stale records destroy trust in the whole system. Relationship memory is the core asset of a brokerage.

**Typical data model:**
- `Contact` (name, emails[], phones[], title, address, owner_user_id, source, status, tags, lifecycle_stage)
- `Account/Company` (name, type, website, address, parent_account_id, owner_user_id)
- `ContactAccountRole` (contact_id, account_id, role, is_primary, start/end date) - many-to-many matters
- `Address`, `Email`, `Phone` as child records (multiple per contact)
- `Tag`/`List`/`Segment`
- Duplicate-detection keys and merge log

**Who does it well:**
- SF: Account/Contact/Account-Contact-Relation (many-to-many), hierarchy, duplicate rules, merge.
- HS: Contacts/Companies with automatic association and timeline, strong dedupe by email/domain.
- PD: People/Organizations, simple and fast.
- ZO: Contacts/Accounts with dedupe and merge tools.
- FUB: People-centric, with automatic lead-source and activity timeline, smart lists.
- Apto: Contacts and Companies tuned for CRE, with relationship mapping and ownership/contact-to-property links.

**Table-stakes checklist:** multi-email/phone, company hierarchy, many-to-many contact/company, dedupe + merge, owner field, tags, timeline view, relationship (who-knows-whom) visibility.

**CRE application:** Contacts include property owners, principals of LLCs, buyers, tenants, lenders, attorneys, and investors. Owners often hold property through multiple LLCs/entities, so the account model needs an entity-to-principal graph (Owner person -> LLC -> property), not a flat company field. Track the decision-maker versus the representative (asset manager, family office staffer). Syndicator/investor relationships need a distinct contact type with investment criteria, accreditation status, and commitment history. Apto and Salesforce-based builds handle this best; HubSpot/Pipedrive need custom objects.

---

## 2. Leads

**What it is:** Unqualified or early-stage prospects tracked before they become a contact/account/deal, with source attribution, status, scoring, assignment, and conversion.

**Why it matters:** Sales needs a triage inbox that measures source quality and speed-to-lead without polluting the clean contact database.

**Typical data model:** `Lead` (name, company, source, status, score, owner, created_at, converted_at) with conversion creating Contact + Account + (optional) Deal; `LeadSource`, `Campaign`, `LeadAssignmentRule`, web-form submission records.

**Who does it well:**
- SF: distinct Lead object, conversion, assignment rules, web-to-lead.
- ZO: Leads module with conversion and scoring (Zia).
- HS: no separate lead object; uses lifecycle stage / lead status on contacts (a design alternative).
- PD: Leads Inbox as a staging area before deals.
- FUB: lead routing, round-robin, speed-to-lead alerts, lead-source integrations (Zillow etc.) - best-in-class for residential.

**Table-stakes checklist:** web form capture, source tracking, assignment/round-robin, status lifecycle, conversion, basic scoring, duplicate check on entry.

**CRE application:** Inbound leads are mostly listing inquiries (CoStar/LoopNet, Crexi, OM/CA downloads, website), plus outbound prospecting lists (owners from public records / data vendors). "Lead" often means a prospective seller/owner (listing origination) rather than buyer. Two lead streams should be distinguishable: seller-side (listing pipeline) and buyer-side (inquiries per listing). Buildout natively captures listing inquiries and OM/CA activity; Apto ties inquiries to properties.

---

## 3. Deals / Pipeline

**What it is:** Opportunities with value, stage, close date, owner, and probability, shown as a configurable stage-based pipeline (kanban) with forecasting.

**Why it matters:** This is how revenue is predicted and where management attention goes. Stage discipline reveals stalled deals.

**Typical data model:** `Deal/Opportunity` (name, amount, stage_id, pipeline_id, probability, expected_close, actual_close, owner, source, lost_reason), `Pipeline`, `Stage` (order, probability, rotting days), `DealContactRole` (deal_id, contact_id, role), `DealStageHistory`, `Product/LineItem` (optional), `Team/Split`.

**Who does it well:**
- PD: the visual kanban pipeline is its core strength; stage rotting indicators, multiple pipelines.
- HS: drag-and-drop deal boards, multiple pipelines, weighted forecast.
- SF: Opportunities with stages, forecasting, opportunity teams and splits, products.
- ZO: Deals/Blueprints for enforced process.
- FUB: Deals tied to people, simpler (transaction-oriented).
- Apto, Buildout: CRE deal records tied to properties/listings with commission tracking.

**Table-stakes checklist:** multiple pipelines, stage history (time-in-stage), weighted forecast, multiple contacts per deal with roles, lost reasons, commission/fee fields, team splits.

**CRE application:** Deal types differ and need separate pipelines: (a) listing/seller-side (prospect -> pitch -> listing agreement -> marketing -> offers -> under contract -> due diligence -> close), (b) buyer-rep, (c) debt/capital placement, (d) leasing. Value is a sale price and a commission/fee, not a single amount; need both, plus co-broker and agent splits. Deals link to Property, multiple parties (seller, buyer, lender, attorney, title, 1031 exchange party), and key dates (listing expiration, DD period, closing). Long cycles (6-18 months) make stage history and next-touch reminders important.

---

## 4. Activities and Tasks

**What it is:** Logged interactions (calls, emails, meetings, notes) and forward-looking to-dos with due dates, assigned to a user and associated to records.

**Why it matters:** Follow-through is the main behavior CRMs exist to enforce; logged activity feeds reporting on rep productivity and relationship recency.

**Typical data model:** `Activity` (type, subject, body, due_at, completed_at, assignee, status, priority, outcome), polymorphic `ActivityAssociation` (activity_id, record_type, record_id) to contact/account/deal/property, `Reminder`, `Recurrence`, `Sequence/Cadence` templates.

**Who does it well:**
- PD: activity-based selling; every deal should have a next scheduled activity.
- HS: tasks, sequences, queues, call logging.
- SF: Tasks/Events, Einstein Activity Capture, cadences (High Velocity Sales).
- FUB: action plans (automated task sequences), smart calling/texting.
- ZO: activities plus Cadences.

**Table-stakes checklist:** tasks with due dates and reminders, call/meeting logging, association to multiple records, overdue views, templates/recurrence, today/this-week agenda.

**CRE application:** Heavy on calls and in-person tours/site visits, recurring "check-in with owner every 90 days" cadences, and tasks keyed to deal milestones (DD expiry, loan contingency). Association to Property plus Contact plus Deal simultaneously is essential. Call-heavy teams value click-to-call and quick call-outcome logging (left voicemail, spoke, no answer) for owner prospecting campaigns.

---

## 5. Notes

**What it is:** Free-text records attached to contacts, accounts, deals, or properties, ideally with @mentions, pinning, attachments, and visibility controls.

**Why it matters:** Tribal knowledge (owner's motivation, family situation, hold-period intent) is the real value in relationship businesses; it must survive broker turnover.

**Typical data model:** `Note` (body, author, created_at, pinned, visibility), `NoteAssociation` (polymorphic), `Attachment/File`, `Mention`.

**Who does it well:** HS (pinned notes, mentions), PD (notes with pinned, attachments), SF (Notes/Enhanced Notes, Chatter), ZO (notes, attachments), FUB (notes with @mentions and team notifications).

**Table-stakes checklist:** rich text, attach to multiple records, timestamped author, @mention, pin, searchable, private-versus-team visibility.

**CRE application:** Capture owner motivation, debt maturity/hold period, tenant roll info, pricing expectations, "do not contact" preferences. Notes should be searchable across the firm so a new broker can see all prior owner conversations. Consider structured fields for key facts so they are filterable rather than buried in notes.

---

## 6. Email and Calendar Sync

**What it is:** Two-way sync with Gmail/Google Workspace and Microsoft 365/Outlook so emails and meetings are auto-logged against the right records, with templates, tracking, and scheduling links.

**Why it matters:** Brokers will not manually log. Auto-capture is the difference between a CRM that is used and one that is abandoned.

**Typical data model:** `EmailAccountConnection` (OAuth tokens, scopes, sync state), `EmailMessage` (thread_id, from, to[], cc[], subject, body, sent_at, direction), `EmailAssociation` (matched contacts/deals), `CalendarEvent` (attendees, start/end, location, linked records), `EmailTemplate`, `TrackingEvent` (open/click), `ExclusionRule` (personal/domain exclusions), `Sequence`.

**Who does it well:**
- HS: Gmail/Outlook integration, tracking, sequences, meeting links.
- SF: Einstein Activity Capture, Outlook/Gmail side panel, Inbox.
- PD: Email sync, smart BCC, scheduler.
- ZO: Gmail/Outlook sync, ZohoMail.
- FUB: email/text/call logging with shared team inbox.
- Apto: Outlook/Gmail sync tuned for brokers.

**Table-stakes checklist:** OAuth 2-way sync, auto-association by email address, privacy controls (exclude personal threads), shared vs private visibility, templates and merge fields, open/click tracking, calendar event sync, scheduling links, BCC-to-CRM fallback.

**CRE application:** Brokers live in Outlook; Microsoft 365 sync quality is decisive. Privacy controls matter since principals negotiate confidentially (NDA/CA). Sync should associate emails with multiple deals/properties and surface "last contact date" and "who in the firm last spoke to this owner" for relationship coverage. Email blasts to investor lists (listing marketing) need bulk send, unsubscribe, and compliance (CAN-SPAM); Buildout and Constant Contact/Mailchimp-style integrations are common.

---

## 7. Reporting Basics

**What it is:** Standard reports and dashboards on pipeline, activity, sources, and conversion, with filters, grouping, and scheduled delivery.

**Why it matters:** Managers need visibility on pipeline health and rep activity; leadership needs forecasts; reports reveal what is working.

**Typical data model:** Reports run on core entities plus `DealStageHistory`, `Activity`, `LeadSource`. Metadata: `Report` (definition, filters, grouping), `Dashboard`, `DashboardWidget`, `Schedule`. Needs history/snapshot tables for trend reporting.

**Who does it well:** SF (most powerful report builder, cross-object, dashboards), HS (custom report builder, attribution on higher tiers), PD (Insights, goals, forecasting), ZO (Analytics, Zia), FUB (agent leaderboards, lead-source ROI).

**Table-stakes checklist:** pipeline by stage/owner, weighted forecast, win/loss, activity counts per user, lead-source performance, time-in-stage, closed volume vs goal, filters and CSV export, scheduled email of reports.

**CRE application:** Key CRE reports: pipeline by property type and market, expected commission by close date, listings by status and days on market, owner-contact recency (who has not been touched in 90 days), broker production (GCI) and splits, buyer interest per listing (inquiries, OM/CA/tour counts), investor-capital-raised summaries for syndication deals. Commission forecasting and GCI by broker are often more important than "deal amount".

---

## 8. Import / Export

**What it is:** Bulk loading (CSV/Excel) with field mapping, dedupe rules, and update-vs-create modes; export of any list; API/integration-based sync; migration tooling.

**Why it matters:** Teams arrive with spreadsheets, prior CRM data, and purchased lists; data portability reduces lock-in risk and lets analysts work outside the tool.

**Typical data model:** `ImportJob` (file, mapping, mode, status, row_errors), `ExportJob`, `FieldMapping`, `ExternalId` (id mapping from source system), `AuditLog`. Public REST API plus webhooks.

**Who does it well:** HS (guided import with association across objects), SF (Data Import Wizard, Data Loader, strong API), PD (CSV/Excel import with mapping, migration help), ZO (import/export, migration tools), FUB (CSV import, integrations).

**Table-stakes checklist:** CSV/XLSX import with mapping, preview, dedupe on key fields (email, external id), update-existing option, error report, import of related records (contact-company-deal), full export by object/view, API access, undo/rollback.

**CRE application:** Common sources: CoStar exports, public-record owner lists (county records, data vendors like Reonomy/PropertyRadar), broker spreadsheets, Outlook contacts. Import needs to handle one-owner-many-properties and entity (LLC) matching. Preserve provenance (source, import date) and allow bulk update from refreshed data feeds. Exports need to include relationship history so the firm retains its asset if it changes systems.

---

## 9. Permissions and Security

**What it is:** Role-based access control over who can see, edit, delete, and export which records and fields, plus audit logging, SSO/MFA, and team structures.

**Why it matters:** Protects confidential client info, limits departing-broker data exfiltration, and supports compliance.

**Typical data model:** `User`, `Role`/`Profile`, `Permission` (object/field/action), `Team`/`Group`, `RoleHierarchy`, `SharingRule`, `RecordVisibility`, `AuditLog`, `ApiToken`, `SSOConfig`.

**Who does it well:** SF (profiles, permission sets, role hierarchy, sharing rules, field-level security, the most granular), HS (teams, permission sets, field-level on higher tiers), PD (visibility groups, permission sets), ZO (profiles/roles, field-level), FUB (roles, lead-routing visibility, ownership transfer).

**Table-stakes checklist:** roles (admin/manager/rep/read-only), record ownership with transfer/reassign, team-level visibility, field-level permissions (e.g., hide commission), export restrictions, audit log, SSO/MFA, deactivate-user with reassignment.

**CRE application:** Brokerages debate "open vs private" books: some want firm-wide visibility of owner relationships (to avoid conflicting outreach), others protect each broker's book. Needs per-record sharing plus shared "firm" views. Confidential deal info (NDA parties, buyer identities, commissions, seller-side pricing) needs field-level restriction. Investor/LP data may carry additional privacy obligations. Offboarding must reassign records and revoke export.

---

## 10. Search

**What it is:** Global search across records and fields, filters/saved views/lists, and quick lookup by name, email, phone, address, or tag.

**Why it matters:** Speed of retrieval determines adoption; users abandon tools where they cannot instantly find "that owner of the building on Main St."

**Typical data model:** Search index over entities (full-text plus phonetic/fuzzy for names), `SavedFilter/View` (criteria JSON), `Segment/List` (dynamic and static), `RecentItems`, `Tag`.

**Who does it well:** HS (global search plus rich filtered views), SF (global search, list views, SOSL), PD (global search plus filters), ZO (global search and filters), FUB (smart lists), Apto (property/contact/company search tuned for CRE).

**Table-stakes checklist:** global typeahead search, filter builder with AND/OR across fields and related records, saved views, dynamic lists/segments, phone/email normalization, fuzzy name match, search by address/APN.

**CRE application:** Must search by property address, APN, entity name, and owner principal interchangeably ("who owns 123 Main?" and "what does John Smith own?"). Filter by property type, size (SF/units/acres), market/submarket, asset class, hold period, lender maturity, investor criteria. Geographic/map-based search is a differentiator but is increasingly expected in CRE.

---

## 11. Custom Fields and Objects

**What it is:** Admin-configurable additional fields (text, number, currency, date, picklist, multi-select, lookup, formula) and, in better systems, entire custom objects, layouts, and validation rules.

**Why it matters:** No vertical fits stock fields. Customization is how a generic CRM becomes a CRE CRM without code.

**Typical data model:** Metadata tables: `FieldDefinition` (object, name, type, options, required, visibility), `ObjectDefinition`, `Layout`, `ValidationRule`, `FormulaField`, `Relationship` definitions; values stored as columns, JSON, or EAV.

**Who does it well:** SF (custom objects, formulas, flows, deepest), HS (custom properties on all tiers; custom objects on Enterprise), ZO (custom modules and fields, Blueprint), PD (custom fields on all objects; limited custom objects), FUB (limited custom fields; less flexible). Apto and Buildout are pre-customized for CRE.

**Table-stakes checklist:** field types incl. picklist/multi-select/lookup/currency/date, required and conditional fields, per-pipeline fields, layouts per role, field history, custom objects (for Property), validation.

**CRE application:** Needed: a first-class `Property` object (address, APN, type, size, year built, units, NOI, cap rate, zoning, lender, loan maturity), `Listing`, `Entity (LLC)`, `Investor Criteria`, `Fund/Syndication` records. Without custom objects, teams cram property data into contact fields and the model breaks. Prefer a platform supporting custom objects with many-to-many associations.

---

## 12. Mobile

**What it is:** Native iOS/Android apps (or responsive web) giving access to contacts, deals, tasks, notes, calls, and offline capture, with push notifications.

**Why it matters:** Brokers are in cars, at site tours, and at meetings; field data entry and caller-ID context determine whether the CRM is current.

**Typical data model:** No new entities; requires sync/offline cache, `Device`/push token, deep links, voice-note/photo `Attachment`, location check-in (optional), click-to-call/text logging.

**Who does it well:** PD (clean, fast mobile app, call logging), HS (solid app, caller ID, business-card scanner), SF (Salesforce mobile, configurable but heavier), ZO (mobile with offline and voice notes), FUB (strong mobile calling/texting for agents), Apto (mobile for brokers).

**Table-stakes checklist:** view/edit contacts and deals, create tasks/notes, click-to-call and call logging, caller ID lookup, push reminders, document/photo attach, offline read at minimum, voice-to-text notes, quick-add.

**CRE application:** Site-visit notes, photos of properties, quick owner lookup from the street ("who owns this building?") via address/geo search, and caller-ID on inbound calls from owners are the highest-value mobile functions. Voice-to-note after a meeting drives data capture.

---

## Cross-cutting items often treated as table stakes

- **Duplicate management and data hygiene** (merge, validation, enrichment).
- **Workflow/automation basics** (assignment rules, reminders, stage-change triggers).
- **Integrations/API** (email, calendar, e-sign, accounting, marketing, data vendors) and Zapier-style connectors.
- **Document storage** (OMs, CAs, LOIs, PSAs attached to deal/property).
- **Audit trail** for compliance and dispute resolution.

---

## CRE Brokerage / Investment-Sales: Core Entity Model Summary

The generic Contact/Account/Deal model breaks down for CRE. Minimum viable model:

| Entity | Purpose | Key relationships |
|---|---|---|
| Contact (person) | Owners, buyers, investors, lenders, attorneys | many-to-many to Company, Property, Deal |
| Company / Entity | LLCs, funds, family offices, brokerages, lenders | principals (contacts), owned properties |
| Property | Asset record with physical and financial attributes | owners (via entity, with dates), listings, deals |
| Listing / Mandate | Engagement to sell/lease a property | property, seller, broker team, marketing activity |
| Deal | Transaction (sale, lease, capital raise) with fee/commission | property, parties and roles, stage history, splits |
| Buyer Interest / Inquiry | Per-listing buyer engagement (CA signed, OM downloaded, tour, offer) | listing, contact, activity |
| Investor Profile | Criteria (asset class, geography, check size, 1031 status, accreditation) | contact/company, commitments |
| Fund / Syndication | Capital raise vehicle and investor commitments | investors, properties, deals |
| Activity / Task / Note / Email | Interaction history | polymorphic to all of the above |
| Document | OM, CA, LOI, PSA, rent roll | deal, listing, property |

### Vendor fit summary for CRE

| Vendor | CRE fit | Notes |
|---|---|---|
| Apto | High | CRE-native objects (properties, deals, comps), broker workflows; on Salesforce platform |
| Buildout | High for listings/marketing | Listing marketing, OM/CA workflow, inquiry capture, deal tracking; lighter as a pure relationship CRM |
| Salesforce | High if customized | Custom objects, many-to-many, fine permissions; needs implementation partner; large CRE ISV ecosystem |
| HubSpot | Medium | Easy to use and adopt; custom objects (Enterprise) can model Property; weaker on many-to-many ownership graphs |
| Pipedrive | Low-medium | Excellent pipeline UX; limited custom objects; fine for small teams |
| Zoho | Medium | Customizable and cost effective; custom modules; smaller CRE ecosystem |
| Follow Up Boss | Low for CRE | Residential lead-routing/speed-to-lead oriented; useful design inspiration for follow-up cadences, not CRE data model |
| Juniper Square / investor-relations tools | Complement | Investor portal, capital calls, distributions; for syndicator/LP relationships post-close rather than prospecting |

### Priority for a CRE build (suggested MVP order)

1. Contact + Entity + Property with many-to-many ownership and dedupe.
2. Deal pipelines (seller-side, buyer-side, capital) with commission and splits.
3. Activities/tasks/notes associated to contacts, properties and deals; cadence reminders.
4. Outlook/Google email and calendar auto-capture with privacy controls.
5. Search by address/APN/entity/owner plus saved lists.
6. Import/export with provenance and dedupe.
7. Permissions (firm-open versus private books, field-level for commissions).
8. Custom fields/objects; baseline reports (pipeline, GCI forecast, owner recency).
9. Mobile quick-add, caller ID and voice notes.

Open questions to verify with live research or the team: which email platform (M365 vs Google), whether firm-wide visibility of owner relationships is desired, data vendors for owner/property data, and whether investor-relations (post-close LP reporting) is in scope or handled by a separate tool.

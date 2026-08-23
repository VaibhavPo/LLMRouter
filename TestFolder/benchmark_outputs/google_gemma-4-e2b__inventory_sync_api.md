# google/gemma-4-e2b — inventory_sync_api

Turns used: 4
Facts recovered: 5/10

## Transcript

**interviewer:**
That sounds like an interesting internal system. To make sure we build exactly what you need, I need to understand the scope and the operational context better.

I have several initial clarifying questions:

1.  **Data Scope:** What exactly constitutes a "stock count"? Are we tracking individual SKUs (Stock Keeping Units), product types, or something else?
2.  **Warehouses:** How many warehouses are we talking about, and what information do we need to store about each warehouse (e.g., location, ID)?
3.  **Source of Truth:** Where will the master record for stock counts originate? Is there an existing system that these counts must sync *from*, or is this service the primary source of truth?
4.  **Synchronization Frequency & Latency:** How frequently must the stock counts be synchronized across warehouses (e.g., real-time, every minute, hourly batch)? What level of acceptable latency is required?
5.  **Update Mechanism:** How will updates to stock counts occur? Will this service handle direct updates from other systems, or will it rely on an event stream or polling mechanism?
6.  **API Consumers:** Who will be consuming this API? (e.g., internal warehouse management systems, reporting tools, external services?)
7.  **Error Handling & Consistency:** What happens if a synchronization fails, or if there is a conflict in the data between warehouses? How should the system handle eventual consistency versus strong consistency?

Please take your time to answer these so we can define the boundaries of the project.

**simulated_user:**
For data scope, we will be tracking individual SKUs across the warehouses. We need to store basic warehouse identifiers and their associated stock levels.

We are planning for exactly three warehouses, each with a distinct update frequency: hourly, every 15 minutes, and on-demand.

The master record for stock counts will originate from this service, as it will be the central point for synchronization.

Synchronization happens via polling mechanisms based on these defined frequencies, which is acceptable given the requirements.

The system will handle updates through a mechanism that allows different sources to feed data into the central store, and every sync event will be logged with a timestamp and source warehouse.

The API will serve internal consumers, supplemented by a simple internal dashboard.

For error handling, conflicts between stock counts will resolve using a 'last write wins' strategy, unless the SKU is high-value (over $10k), in which case it flags for manual review.

**interviewer:**
Thank you for providing those crucial details. This gives us a much clearer picture of the functional and consistency requirements.

I have a few follow-up questions to ensure we capture all the necessary constraints before finalizing the scope:

1.  **SKU Value Management:** You mentioned a conflict resolution rule based on an SKU value exceeding $10k. Where will this SKU value information be stored, and how is that threshold managed? Does the service need to handle the storage and retrieval of product metadata, or is it purely focused on stock counts?
2.  **On-Demand Updates:** For the "on-demand" update frequency, what triggers these updates? Is there an external system that signals when a manual sync is required, or does this imply that the service must periodically check for updates from sources at arbitrary times?
3.  **API Endpoints:** What specific operations will the internal consumers need to perform via the API? (e.g., Get stock level for SKU X in Warehouse Y? Update stock level? List all SKUs?)
4.  **Dashboard Data:** What specific data points are required for the "simple internal dashboard"? Is it just aggregated counts, or does it require historical trend data or detailed audit logs?
5.  **Logging Detail:** Regarding the synchronization event logging (timestamp and source warehouse), what other critical information must be recorded for each sync event (e.g., the resulting stock levels, the specific update operation that occurred)?

Once we clarify these points, I believe we will have a solid foundation to define the system architecture.

**simulated_user:**
For SKU value management, the SKU value will be stored as metadata associated with each product record in the database, allowing the service to check the threshold during conflict resolution.

The on-demand updates will be triggered by an external system signaling a manual sync request, meaning the service must be able to accept an explicit trigger for that frequency.

The API endpoints will primarily focus on retrieving stock levels for specific SKUs within specified warehouses and potentially allowing internal updates based on defined permissions.

The internal dashboard will require aggregated stock counts and historical trend data derived from the audit logs to show recent changes.

For logging detail, every sync event must record the timestamp, source warehouse, and the resulting stock levels after the synchronization to ensure full auditability.

**interviewer:**
This is excellent. We have covered the core functional needs, consistency rules, and auditability requirements very well.

I have enough information now to define the scope clearly. Before I proceed to write the full specification, I have one final set of clarifying questions focused on implementation details, specifically around data persistence and access control:

1.  **Data Persistence Strategy:** Since we need historical trend data for the dashboard derived from audit logs, should the system store *only* the current state and the sync logs, or do we need a separate mechanism to store the complete history of all stock level changes?
2.  **Update Permissions (Security):** You mentioned that API updates will be based on defined permissions. Who are the internal consumers, and what level of access control is required for updating stock levels (e.g., can Warehouse A update counts in Warehouse B, or only its own)?
3.  **Master Data Management:** Since this service is the master source, how will we handle changes to the SKU metadata (the $10k threshold status) if that information originates from an external system? Is there a separate mechanism for managing product master data, or is it static within this service's lifecycle?

Once these final points are addressed, I will proceed with writing the specification.

**simulated_user:**
For data persistence, we should store both the current state of stock counts and the detailed synchronization logs to support historical trend analysis on the dashboard.

Regarding update permissions, access control will be based on warehouse ownership; a warehouse can only update its own stock levels within this system.

For master data management, since this service is the primary source, we will initially treat SKU metadata like the $10k threshold as static within this service's lifecycle, with an agreed-upon process for external updates if necessary later.

**interviewer:**
Let me write CONTEXT.md based on what we've discussed:

# CONTEXT.md

## Problem Statement
The objective is to build a small, internal API service designed to act as the central source of truth for synchronizing and managing stock counts across exactly three distinct warehouses. The system must handle different update frequencies per warehouse, ensure data integrity through conflict resolution rules, provide comprehensive auditability, and serve internal consumers via an API and a dashboard.

## Functional Requirements
1.  **Stock Tracking:** The service must store the current stock levels for individual SKUs within each of the three defined warehouses.
2.  **Warehouse Definition:** The system must manage data for exactly three distinct warehouses, each with a unique identifier.
3.  **Synchronization Logic:** The service must implement polling mechanisms to synchronize stock counts based on predefined frequencies: hourly, every 15 minutes, and on-demand.
4.  **Data Ingestion & Logging:** The system must support an internal mechanism for feeding data into the central store from various sources. Every synchronization event must be logged with a timestamp, the source warehouse, and the resulting stock levels after the sync to ensure full auditability.
5.  **API Endpoints:** The service must expose an API to internal consumers, primarily focused on retrieving stock levels for specific SKUs within specified warehouses.
6.  **Internal Dashboard Data:** The system must provide data necessary for an internal dashboard, including aggregated stock counts and historical trend data derived from the synchronization audit logs.
7.  **Conflict Resolution:** When synchronizing data, conflicts between stock counts must be resolved using a 'last write wins' strategy, unless the SKU is flagged as high-value (metadata > $10k), in which case the record must be flagged for manual review instead of automatic resolution.
8.  **Update Permissions:** The API must support internal updates to stock levels, strictly enforced by warehouse ownership; a warehouse can only update its own stock levels within this system.

## Non-Functional Requirements
1.  **Performance (Latency):** Synchronization processes must adhere to their defined frequencies (hourly, 15 min, on-demand). The API retrieval operations should be highly performant for internal consumers.
2.  **Auditability:** All synchronization events and resulting stock levels must be immutably logged.
3.  **Consistency:** The system must maintain eventual consistency across all warehouses, governed by the defined conflict resolution strategy.
4.  **Security/Access Control:** Access to update endpoints must be strictly controlled based on warehouse ownership.

## Assumptions
1.  The SKU metadata (e.g., $10k threshold status) is static within the service's lifecycle and will not be dynamically updated by external systems during this phase.
2.  The synchronization mechanism relies solely on polling triggered by the system itself or an external signal for on-demand updates.
3.  Internal consumers are trusted entities operating within the organization.

## Risks and Constraints
*   **Risk:** Inaccurate handling of the "last write wins" conflict resolution, especially concerning high-value SKUs. (Mitigated by strict adherence to the defined rule).
*   **Constraint:** The system is strictly limited to exactly three warehouses initially.
*   **Constraint:** The initial implementation focuses on internal use; external security standards are secondary to internal access control rules.

## Design Trade-offs (Decisions Made and Why)
*   **Conflict Resolution Strategy (Last Write Wins vs. Manual Flag):** We chose 'last write wins' as the default for


#!/usr/bin/env python3
"""Enable actual native Vue-Flow editing in n8n's isolated preview canvas only.

n8n upstream v2.44.5 pins the /workflows/demo route to read-only. This patch
reuses *upstream* NodeView, Canvas, NodeCreation and NodeDetails components.
Changes are intentionally scoped to ?editable=true and N8N_PREVIEW_MODE=true.
Never change normal /workflow/* permission checks or backend auth routes.

Saved draft is sent via postMessage to our same-origin test portal, which
persists it in the browser and reloads it after refresh. No real orders and
no credentials. The portal clearly labels this as browser-local draft storage.
"""
from pathlib import Path

root = Path("/src/n8n/packages/frontend/editor-ui/src")
changes = []

def edit(relpath, replacements):
    path = root / relpath
    original = path.read_text(encoding="utf-8")
    text = original
    for marker, replacement in replacements:
        hits = text.count(marker)
        if hits != 1:
            raise RuntimeError(f"Expected one match in {relpath}; found {hits} for {marker[:110]!r}")
        text = text.replace(marker, replacement, 1)
    path.write_text(text, encoding="utf-8")
    changes.append(str(path) + f" ({len(replacements)} anchored changes)")
    if text == original:
        raise RuntimeError("No modification " + str(path))

edit("app/views/NodeView.vue", [
    (
        "const isDemoRoute = computed(() => route.name === VIEWS.DEMO);",
        """const isDemoRoute = computed(() => route.name === VIEWS.DEMO);
// Editable workflow test ONLY on our isolated upstream preview instance.
// Do not grant editing to authenticated production workflows or normal demo links.
const isNativeEditableTest = computed(
    () => settingsStore.isPreviewMode && isDemoRoute.value && route.query.editable === 'true',
);""",
    ),
    (
        """const isCanvasReadOnly = computed(() => {
	return (
		isDemoRoute.value ||""",
        """const isCanvasReadOnly = computed(() => {
    if (isNativeEditableTest.value) return false;
	return (
		isDemoRoute.value ||""",
    ),
    (
        """async function onSaveWorkflow() {
	await workflowSaving.saveCurrentWorkflow({});
}""",
        """async function onSaveWorkflow() {
    if (isNativeEditableTest.value) {
        if (window.parent && workflowDocumentStore.value) {
            window.parent.postMessage(
                JSON.stringify({
                    command: 'testWorkflowSnapshot',
                    workflow: workflowDocumentStore.value.serialize(),
                }),
                window.location.origin,
            );
        }
        return;
    }
	await workflowSaving.saveCurrentWorkflow({});
}""",
    ),
    (
        """function checkIfEditingIsAllowed(): boolean {
	if (!uiStore.nodeViewInitialized) {""",
        """function checkIfEditingIsAllowed(): boolean {
    // Allow native drag, add, delete, connect, rename and NDV editing for
    // the isolated browser-local test route only.
    if (isNativeEditableTest.value) return true;
	if (!uiStore.nodeViewInitialized) {""",
    ),
]);
edit("app/router.ts", [
    (
        "route.meta.readOnlyCanvas = !EDITABLE_CANVAS_VIEWS.includes((route?.name ?? '') as VIEWS);",
        """route.meta.readOnlyCanvas =
        route?.name !== VIEWS.DEMO &&
        !EDITABLE_CANVAS_VIEWS.includes((route?.name ?? '') as VIEWS);""",
    ),
]);
edit("app/composables/usePostMessageHandler.ts", [
    (
        """} else if (json?.command === 'resetWorkflow') {
				resetWorkspace();""",
        """} else if (json?.command === 'saveTestWorkflow') {
                // Same-origin portal requests current REAL n8n document snapshot.
                if (route.name === VIEWS.DEMO && route.query.editable === 'true') {
                    const doc = currentWorkflowDocumentStore.value;
                    if (doc && window.parent) {
                        window.parent.postMessage(
                            JSON.stringify({
                                command: 'testWorkflowSnapshot',
                                workflow: doc.serialize(),
                            }),
                            window.location.origin,
                        );
                    }
                }
            } else if (json?.command === 'resetWorkflow') {
				resetWorkspace();""",
    ),
]);
# Provide a visible portal button which opens the official n8n NodeCreator.
# No replacement graph or synthetic Vue nodes: everything is delegated to
# upstream NodeView / useCanvasOperations. Test node is specifically NoOp.
edit("app/views/NodeView.vue", [
    (
        """function onOpenNodeCreatorFromCanvas(source: NodeCreatorOpenSource) {
	onToggleNodeCreator({ createNodeActive: true, source });
}""",
        """function onOpenNodeCreatorFromCanvas(source: NodeCreatorOpenSource) {
	onToggleNodeCreator({ createNodeActive: true, source });
}

// Dedicated parent-initiated controls for the isolated native edit test.
async function onNativeEditTestMessage(event: MessageEvent) {
    if (!isNativeEditableTest.value || event.origin !== window.location.origin ||
        event.source !== window.parent || typeof event.data !== 'string') return;

    let command: string | undefined;
    try {
        const message = JSON.parse(event.data) as { command?: string };
        command = message.command;
    } catch { return; }

    if (command !== 'openNativeNodeCreator' && command !== 'addNativeTestNode') return;

    try {
        if (command === 'openNativeNodeCreator') {
            // Show the ORIGINAL n8n searchable node list, not a custom picker.
            nodeCreatorStore.openNodeCreatorForRegularNodes(
                workflowId.value, NODE_CREATOR_OPEN_SOURCES.NODE_SHORTCUT,
            );
        } else {
            // Use the original n8n insertion method so the node participates in
            // VueFlow rendering, native history, NDV editing and serialization.
            await onAddNodesAndConnections({
                nodes: [{ type: 'n8n-nodes-base.noOp', openDetail: false }],
                connections: [],
            });
        }
        window.parent.postMessage(JSON.stringify({
            command: 'nativeTestUiResult',
            action: command,
            nodes: workflowDocumentStore.value.allNodes.length,
            nodeCreatorOpen: nodeCreatorStore.isCreateNodeActive,
        }), window.location.origin);
    } catch (err) {
        window.parent.postMessage(JSON.stringify({
            command: 'nativeTestUiResult',
            action: command,
            error: err instanceof Error ? err.message : String(err),
        }), window.location.origin);
    }
}""",
    ),
    (
        """onMounted(async () => {
	// Register callback for collaboration store to refresh canvas when workflow updates arrive""",
        """onMounted(async () => {
    window.addEventListener('message', onNativeEditTestMessage);
	// Register callback for collaboration store to refresh canvas when workflow updates arrive""",
    ),
    (
        """onBeforeUnmount(() => {
	isUnmounted = true;""",
        """onBeforeUnmount(() => {
    window.removeEventListener('message', onNativeEditTestMessage);
	isUnmounted = true;""",
    ),
]);

# n8n's global Ctrl+Z handler checks getNodeViewTab(route). The original
# demo route does not have meta.nodeView, therefore a test editor can delete
# nodes but undo/redo never receives history events. Treat ONLY editable demo
# routes as workflow views for keyboard history.
edit("app/utils/nodeViewUtils.ts", [
    (
        """if (route.meta?.nodeView) {
		return MAIN_HEADER_TABS.WORKFLOW;""",
        """if (
        route.meta?.nodeView ||
        (route.name === VIEWS.DEMO && route.query.editable === 'true')
    ) {
		return MAIN_HEADER_TABS.WORKFLOW;""",
    ),
]);

# The upstream global history shortcut does not undo deletions on the
# editable demo route in the real Chrome E2E, despite native history records.
# Install a scoped capturing handler that invokes the SAME original
# history-store commands (revert / reverse) used by useHistoryHelper.
edit("app/views/NodeView.vue", [
    (
        "import { AddNodeGroupCommand, historyBus } from '@/app/models/history';",
        "import { AddNodeGroupCommand, BulkCommand, Command, historyBus } from '@/app/models/history';",
    ),
    (
        "// Dedicated parent-initiated controls for the isolated native edit test.",
        """// Native keyboard undo/redo on the isolated editable demo only.
async function onNativeEditTestHistoryKeydown(event: KeyboardEvent) {
    if (!isNativeEditableTest.value || !event.ctrlKey ||
        event.key.toLowerCase() !== 'z' || event.repeat) return;
    const el = event.target;
    if (el instanceof HTMLElement && (
        el.isContentEditable || ['INPUT', 'TEXTAREA'].includes(el.tagName)
    )) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    const undo = !event.shiftKey;
    const cmd = undo ? historyStore.popUndoableToUndo() : historyStore.popUndoableToRedo();
    if (!cmd) return;
    const now = Date.now();
    if (cmd instanceof BulkCommand) {
        historyStore.bulkInProgress = true;
        try {
            const reversals: Command[] = [];
            for (let i = cmd.commands.length - 1; i >= 0; i--) {
                await cmd.commands[i].revert();
                reversals.push(cmd.commands[i].getReverseCommand(now));
            }
            if (undo) historyStore.pushUndoableToRedo(new BulkCommand(reversals));
            else historyStore.pushBulkCommandToUndo(new BulkCommand(reversals), false);
            await nextTick();
        } finally { historyStore.bulkInProgress = false; }
    } else if (cmd instanceof Command) {
        await cmd.revert();
        if (undo) historyStore.pushUndoableToRedo(cmd.getReverseCommand(now));
        else historyStore.pushCommandToUndo(cmd.getReverseCommand(now), false);
        uiStore.markStateDirty();
    }
}

// Dedicated parent-initiated controls for the isolated native edit test.""",
    ),
    (
        "    window.addEventListener('message', onNativeEditTestMessage);",
        "    window.addEventListener('message', onNativeEditTestMessage);\n    document.addEventListener('keydown', onNativeEditTestHistoryKeydown, true);",
    ),
    (
        "    window.removeEventListener('message', onNativeEditTestMessage);",
        "    window.removeEventListener('message', onNativeEditTestMessage);\n    document.removeEventListener('keydown', onNativeEditTestHistoryKeydown, true);",
    ),
]);

print("\n".join(changes))
print("NATIVE_N8N_EDIT_PATCH_OK")

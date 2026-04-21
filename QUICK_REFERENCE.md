# 🎯 Quick Reference: Context-Aware Toolbar System

## Component Structure

### 1. Top Action Bar (Always Visible)
**Location**: Top-left and top-right of canvas
**Purpose**: Essential actions that are always needed

```javascript
// Left side
- Add Text Button (addTextBoxBtn)
- Undo Button (undoBtn)
- Redo Button (redoBtn)

// Right side
- Zoom Out (zoomOutBtn)
- Zoom Label (zoomLabel)
- Zoom In (zoomInBtn)
- Fit to View (zoomResetBtn)
- Save Button (saveDesignBtn)
```

---

### 2. Context Toolbar (Conditional)
**Location**: Floats near selected object
**Purpose**: Show only relevant controls for selected object

```javascript
// Container
contextToolbar (id="contextToolbar")
  ├── textControls (id="textControls") - Hidden by default
  ├── imageControls (id="imageControls") - Hidden by default
  └── commonControls (id="commonControls") - Always visible when toolbar shows
```

---

## Behavior Logic

### Show/Hide Rules:
```javascript
// HIDE toolbar when:
- No object is selected
- Artboard is selected
- Canvas is clicked (deselect)

// SHOW toolbar when:
- Any object is selected
- Multiple objects are selected

// TEXT controls visible when:
- Selected object is IText, Text, or Textbox

// IMAGE controls visible when:
- Selected object is Image, Group, or SVG
- NOT a text object
```

---

## Key Functions

### `updateContextToolbar()`
**Purpose**: Main function that controls toolbar visibility and positioning

```javascript
function updateContextToolbar() {
  // 1. Check if anything is selected
  // 2. If nothing → hide toolbar
  // 3. If selected → show toolbar
  // 4. Position toolbar near object
  // 5. Show/hide specific controls based on type
}
```

**Called on**:
- `selection:created`
- `selection:updated`
- `selection:cleared`
- `object:moving`
- `object:scaling`
- `object:rotating`

---

### `updateTextToolbarState(selectedObj)`
**Purpose**: Update text control values to match selected text

```javascript
function updateTextToolbarState(selectedObj) {
  // Updates:
  - Font family dropdown
  - Font size input
  - Text color picker
  - Bold/Italic button states
  - Alignment button states
}
```

---

### Add Text Box Button
**ID**: `addTextBoxBtn`
**Behavior**:
```javascript
1. Create new IText object
2. Position at canvas center
3. Add to canvas
4. Set as active object
5. Enter editing mode (auto-focus)
6. Select all text
7. Save state for undo
```

---

## Positioning Algorithm

```javascript
// Get object bounds
const objBounds = activeObj.getBoundingRect();
const zoom = canvas.getZoom();
const vpt = canvas.viewportTransform;

// Calculate screen position
let toolbarLeft = objBounds.left * zoom + vpt[4];
let toolbarTop = (objBounds.top * zoom + vpt[5]) - 60; // 60px above

// Keep within canvas bounds
if (toolbarLeft + toolbarWidth > canvasWidth) {
  toolbarLeft = canvasWidth - toolbarWidth - 20;
}
if (toolbarLeft < 20) toolbarLeft = 20;

// If no space above, show below
if (toolbarTop < 80) {
  toolbarTop = (objBounds.top + objBounds.height) * zoom + vpt[5] + 20;
}
```

---

## CSS Classes

### Toolbar States:
```css
.context-toolbar {
  display: none; /* Hidden by default */
}

.context-toolbar.visible {
  display: flex; /* Show when active */
}
```

### Button States:
```css
.ctrl-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.ctrl-btn.is-active {
  border-color: #6366f1;
  background: rgba(99, 102, 241, 0.2);
  color: #a5b4fc;
}
```

---

## Event Flow

### Text Creation:
```
User clicks "Add Text"
  ↓
addTextBoxBtn click event
  ↓
Create IText object
  ↓
Add to canvas
  ↓
Set as active
  ↓
Enter editing mode
  ↓
Context toolbar appears
  ↓
Text controls visible
```

### Object Selection:
```
User clicks object
  ↓
selection:created event
  ↓
updateContextToolbar()
  ↓
Check object type
  ↓
Show relevant controls
  ↓
Position toolbar
  ↓
Update control values
```

### Deselection:
```
User clicks canvas
  ↓
selection:cleared event
  ↓
updateContextToolbar()
  ↓
Hide toolbar
```

---

## Control IDs Reference

### Text Controls:
- `textFontFamily` - Font dropdown
- `textFontSize` - Size input
- `textFillColor` - Color picker
- `textBoldBtn` - Bold toggle
- `textItalicBtn` - Italic toggle
- `.text-align-btn[data-align="left|center|right"]` - Alignment

### Image Controls:
- `itemColorPicker` - Object color
- `flipXBtn` - Flip horizontal
- `flipYBtn` - Flip vertical

### Common Controls:
- `layerUpBtn` - Bring forward
- `layerDownBtn` - Send backward
- `lockBtn` - Lock/unlock
- `cloneBtn` - Duplicate
- `deleteBtn` - Remove

### Top Bar:
- `addTextBoxBtn` - Add text
- `undoBtn` - Undo
- `redoBtn` - Redo
- `zoomOutBtn` - Zoom out
- `zoomInBtn` - Zoom in
- `zoomResetBtn` - Fit to view
- `saveDesignBtn` - Save design

---

## Debugging Tips

### Check toolbar visibility:
```javascript
console.log(contextToolbar.classList.contains('visible'));
```

### Check selected object:
```javascript
const active = canvas.getActiveObject();
console.log('Selected:', active);
console.log('Type:', active?.type);
console.log('Is Text:', isTextObject(active));
```

### Check control visibility:
```javascript
console.log('Text controls:', textControls.style.display);
console.log('Image controls:', imageControls.style.display);
```

### Force toolbar update:
```javascript
updateContextToolbar();
```

---

## Common Issues & Fixes

### Toolbar not showing:
- Check if object is selected: `canvas.getActiveObject()`
- Verify `contextToolbar` element exists
- Check CSS class: `.context-toolbar.visible`

### Wrong controls showing:
- Verify `isTextObject()` function
- Check object type: `obj.type`
- Ensure control divs have correct IDs

### Toolbar positioning off:
- Check zoom level: `canvas.getZoom()`
- Verify viewport transform: `canvas.viewportTransform`
- Ensure canvas bounds are correct

### Add Text not working:
- Check `addTextBoxBtn` exists
- Verify event listener is attached
- Check `getArtboardCenterPointer()` function
- Ensure Fabric.js IText is available

---

## Performance Notes

- Toolbar updates on every object move/scale/rotate
- Use `requestAnimationFrame` if performance issues occur
- Debounce toolbar positioning if needed
- Cache toolbar dimensions to avoid reflow

---

## Accessibility

- All buttons have `title` attributes for tooltips
- Keyboard shortcuts still work (Ctrl+Z, Delete, etc.)
- Color pickers are native inputs (accessible)
- Focus states on all interactive elements

---

**Quick Start**: 
1. Click "Add Text" to create text
2. Select any object to see context toolbar
3. Click away to hide toolbar
4. Use keyboard shortcuts for speed

**Remember**: The toolbar is smart - it only shows what you need, when you need it!

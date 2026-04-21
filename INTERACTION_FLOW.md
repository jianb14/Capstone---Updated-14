# 🔄 Interaction Flow & Behavior Logic

## Overview
This document explains exactly how the context-aware toolbar system works, when it appears, and what controls are shown.

---

## 🎯 Core Behavior Rules

### Rule 1: Toolbar Visibility
```
IF no object selected
  → Hide context toolbar
  
IF object selected AND object is NOT artboard
  → Show context toolbar
  → Position near object
  
IF artboard selected
  → Hide context toolbar
```

### Rule 2: Control Visibility
```
IF selected object is TEXT (IText, Text, Textbox)
  → Show: textControls
  → Hide: imageControls
  → Show: commonControls
  
IF selected object is IMAGE/OBJECT (Image, Group, SVG, Rect, etc.)
  → Hide: textControls
  → Show: imageControls
  → Show: commonControls
  
IF multiple objects selected
  → Show: commonControls only
  → Hide: textControls and imageControls
```

### Rule 3: Toolbar Position
```
1. Get object bounding box
2. Calculate position 60px above object
3. If no space above → show 20px below object
4. Keep within canvas bounds (20px margin)
5. Update position on object move/scale/rotate
```

---

## 📊 State Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     CANVAS STATE                            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │   No Selection   │
                    │  (Initial State) │
                    └──────────────────┘
                              │
                ┌─────────────┼─────────────┐
                │                           │
                ▼                           ▼
        ┌──────────────┐          ┌──────────────┐
        │ User clicks  │          │ User clicks  │
        │   object     │          │   canvas     │
        └──────────────┘          └──────────────┘
                │                           │
                ▼                           ▼
        ┌──────────────┐          ┌──────────────┐
        │   SELECTED   │          │ DESELECTED   │
        │   (Active)   │          │  (Cleared)   │
        └──────────────┘          └──────────────┘
                │                           │
                │                           │
        ┌───────┴───────┐                   │
        │               │                   │
        ▼               ▼                   │
┌──────────┐    ┌──────────┐               │
│   TEXT   │    │  IMAGE   │               │
│ Selected │    │ Selected │               │
└──────────┘    └──────────┘               │
        │               │                   │
        ▼               ▼                   │
┌──────────┐    ┌──────────┐               │
│   Show   │    │   Show   │               │
│   Text   │    │  Image   │               │
│ Controls │    │ Controls │               │
└──────────┘    └──────────┘               │
        │               │                   │
        └───────┬───────┘                   │
                │                           │
                ▼                           │
        ┌──────────────┐                    │
        │ User clicks  │                    │
        │   canvas     │────────────────────┘
        └──────────────┘
                │
                ▼
        ┌──────────────┐
        │ Hide Toolbar │
        └──────────────┘
```

---

## 🎬 Interaction Sequences

### Sequence 1: Adding Text
```
User Action                 System Response                 UI State
───────────────────────────────────────────────────────────────────
1. Click "Add Text"    →    Create IText object        →   Text appears
                            Position at center              at center
                            
2. (Automatic)         →    Set as active object       →   Text selected
                            Enter editing mode              (blue border)
                            
3. (Automatic)         →    Select all text            →   Text highlighted
                            
4. (Automatic)         →    Show context toolbar       →   Toolbar appears
                            Show text controls              above text
                            
5. User types          →    Replace selected text      →   New text shows
                            
6. User clicks away    →    Exit editing mode          →   Toolbar hides
                            Deselect object                 Text finalized
```

### Sequence 2: Editing Existing Text
```
User Action                 System Response                 UI State
───────────────────────────────────────────────────────────────────
1. Click text          →    Select object              →   Text selected
                            
2. (Automatic)         →    Show context toolbar       →   Toolbar appears
                            Show text controls              with text options
                            Update control values           
                            
3. Change font         →    Apply to text              →   Text updates
                            Save state (undo)               live
                            
4. Click Bold          →    Toggle fontWeight          →   Text becomes bold
                            Update button state             Button highlighted
                            
5. Click away          →    Deselect                   →   Toolbar hides
                            Save final state                Changes saved
```

### Sequence 3: Editing Image
```
User Action                 System Response                 UI State
───────────────────────────────────────────────────────────────────
1. Click image         →    Select object              →   Image selected
                            
2. (Automatic)         →    Show context toolbar       →   Toolbar appears
                            Show image controls             with image options
                            Hide text controls              
                            
3. Click Flip H        →    Toggle flipX property      →   Image flips
                            Save state (undo)               horizontally
                            
4. Change color        →    Apply to object            →   Color updates
   (if SVG)                 Update fill property            live
                            
5. Click away          →    Deselect                   →   Toolbar hides
                            Save final state                Changes saved
```

### Sequence 4: Layer Management
```
User Action                 System Response                 UI State
───────────────────────────────────────────────────────────────────
1. Select object       →    Show context toolbar       →   Toolbar visible
                            Enable layer buttons            
                            
2. Click "Forward"     →    Bring object forward       →   Object moves
                            Save state (undo)               up one layer
                            
3. Click "Backward"    →    Send object backward       →   Object moves
                            Save state (undo)               down one layer
                            
4. Click "Lock"        →    Lock object                →   Lock icon changes
                            Disable movement                Object grayed
                            Disable controls                Controls disabled
```

---

## 🔀 Decision Tree

### When Object is Selected:
```
START: Object Selected
│
├─ Is object the artboard?
│  ├─ YES → Hide toolbar → END
│  └─ NO → Continue
│
├─ What type is the object?
│  │
│  ├─ IText / Text / Textbox
│  │  ├─ Show textControls
│  │  ├─ Hide imageControls
│  │  ├─ Show commonControls
│  │  ├─ Update font dropdown
│  │  ├─ Update size input
│  │  ├─ Update color picker
│  │  ├─ Update bold/italic state
│  │  └─ Update alignment buttons
│  │
│  ├─ Image / Group / SVG / Rect / Circle
│  │  ├─ Hide textControls
│  │  ├─ Show imageControls
│  │  ├─ Show commonControls
│  │  └─ Update color picker (if applicable)
│  │
│  └─ Multiple objects
│     ├─ Hide textControls
│     ├─ Hide imageControls
│     └─ Show commonControls only
│
├─ Calculate toolbar position
│  ├─ Get object bounds
│  ├─ Calculate position above object
│  ├─ Check if fits above
│  │  ├─ YES → Position above
│  │  └─ NO → Position below
│  └─ Clamp to canvas bounds
│
└─ Show toolbar with calculated position
   └─ END
```

---

## 🎨 Visual State Changes

### Button States:

#### Normal State:
```css
background: #252932
color: #b4bac7
border: 1px solid #2f3441
```

#### Hover State:
```css
background: #2f3441
color: #e5e7eb
border: 1px solid #3f4551
```

#### Active State (e.g., Bold is ON):
```css
background: rgba(99, 102, 241, 0.2)
color: #a5b4fc
border: 1px solid #6366f1
```

#### Disabled State:
```css
opacity: 0.35
cursor: not-allowed
(no hover effect)
```

---

## 🔄 Event Listeners

### Canvas Events:
```javascript
canvas.on('selection:created', () => {
  updateControlsState();
  updateContextToolbar();
});

canvas.on('selection:updated', () => {
  updateControlsState();
  updateContextToolbar();
});

canvas.on('selection:cleared', () => {
  updateControlsState();
  updateContextToolbar(); // Hides toolbar
});

canvas.on('object:moving', () => {
  updateContextToolbar(); // Reposition toolbar
});

canvas.on('object:scaling', () => {
  updateContextToolbar(); // Reposition toolbar
});

canvas.on('object:rotating', () => {
  updateContextToolbar(); // Reposition toolbar
});
```

### Button Events:
```javascript
// Add Text Button
addTextBoxBtn.click → Create text → Auto-focus

// Text Controls
textFontFamily.change → Update font → Save state
textFontSize.input → Update size (live)
textFontSize.change → Save state
textFillColor.input → Update color (live)
textFillColor.change → Save state
textBoldBtn.click → Toggle bold → Update state
textItalicBtn.click → Toggle italic → Update state
textAlignBtn.click → Set alignment → Save state

// Image Controls
itemColorPicker.input → Update color (live)
itemColorPicker.change → Save state
flipXBtn.click → Flip horizontal → Save state
flipYBtn.click → Flip vertical → Save state

// Common Controls
layerUpBtn.click → Bring forward → Save state
layerDownBtn.click → Send backward → Save state
lockBtn.click → Toggle lock → Update state
cloneBtn.click → Duplicate object → Save state
deleteBtn.click → Remove object → Save state
```

---

## 🎯 Positioning Logic

### Toolbar Position Calculation:
```javascript
// Step 1: Get object bounds in canvas coordinates
const objBounds = activeObj.getBoundingRect();

// Step 2: Get current zoom and viewport transform
const zoom = canvas.getZoom();
const vpt = canvas.viewportTransform;

// Step 3: Convert to screen coordinates
let screenX = objBounds.left * zoom + vpt[4];
let screenY = objBounds.top * zoom + vpt[5];

// Step 4: Position toolbar above object (60px gap)
let toolbarX = screenX;
let toolbarY = screenY - 60;

// Step 5: Get toolbar dimensions
const toolbarWidth = contextToolbar.offsetWidth;
const toolbarHeight = contextToolbar.offsetHeight;

// Step 6: Get canvas dimensions
const canvasWidth = canvas.getElement().getBoundingClientRect().width;
const canvasHeight = canvas.getElement().getBoundingClientRect().height;

// Step 7: Clamp horizontal position
if (toolbarX + toolbarWidth > canvasWidth - 20) {
  toolbarX = canvasWidth - toolbarWidth - 20;
}
if (toolbarX < 20) {
  toolbarX = 20;
}

// Step 8: Check if toolbar fits above
if (toolbarY < 80) {
  // Not enough space above, position below
  toolbarY = (objBounds.top + objBounds.height) * zoom + vpt[5] + 20;
}

// Step 9: Apply position
contextToolbar.style.left = toolbarX + 'px';
contextToolbar.style.top = toolbarY + 'px';
```

---

## 🧪 Testing Scenarios

### Test 1: Basic Text Creation
```
1. Click "Add Text" button
   ✓ Text appears at canvas center
   ✓ Text is selected (blue border)
   ✓ Text is in editing mode (cursor visible)
   ✓ Text is highlighted (ready to replace)
   ✓ Context toolbar appears
   ✓ Text controls are visible
   ✓ Image controls are hidden
```

### Test 2: Text Editing
```
1. Select existing text
   ✓ Context toolbar appears
   ✓ Text controls show
   ✓ Font dropdown shows current font
   ✓ Size input shows current size
   ✓ Color picker shows current color
   ✓ Bold button reflects current state
   ✓ Italic button reflects current state
   ✓ Alignment buttons reflect current alignment
```

### Test 3: Image Selection
```
1. Select image
   ✓ Context toolbar appears
   ✓ Image controls show
   ✓ Text controls hidden
   ✓ Color picker enabled (if SVG)
   ✓ Flip buttons enabled
   ✓ Layer buttons enabled
```

### Test 4: Deselection
```
1. Click canvas (empty area)
   ✓ Context toolbar hides
   ✓ Object deselected
   ✓ Only top action bar visible
```

### Test 5: Toolbar Positioning
```
1. Select object at top of canvas
   ✓ Toolbar appears below object (not above)
   
2. Select object at left edge
   ✓ Toolbar stays within canvas (not cut off)
   
3. Select object at right edge
   ✓ Toolbar adjusts position to fit
   
4. Move object while selected
   ✓ Toolbar follows object
```

---

## 🐛 Common Edge Cases

### Edge Case 1: Rapid Selection Changes
```
Problem: User quickly selects multiple objects
Solution: Toolbar updates on each selection
Result: Smooth transition between control sets
```

### Edge Case 2: Object Near Canvas Edge
```
Problem: Toolbar might go off-screen
Solution: Clamp position with 20px margin
Result: Toolbar always visible
```

### Edge Case 3: Very Small Object
```
Problem: Toolbar might cover object
Solution: Position below if no space above
Result: Object remains visible
```

### Edge Case 4: Multiple Objects Selected
```
Problem: Mixed types (text + image)
Solution: Show only common controls
Result: No confusion about which controls apply
```

### Edge Case 5: Locked Object
```
Problem: User tries to edit locked object
Solution: Disable editing controls, show lock icon
Result: Clear feedback that object is locked
```

---

## 📝 Summary

### Key Takeaways:
1. **Context is King**: Toolbar adapts to selection
2. **Position Matters**: Toolbar follows object
3. **Smart Hiding**: Only show when needed
4. **Type Detection**: Different controls for different objects
5. **Edge Handling**: Always keep toolbar visible and accessible

### The Magic Formula:
```
Selection + Type Detection + Smart Positioning = Context-Aware Toolbar
```

---

**Remember**: The goal is to show the right tools at the right time in the right place! 🎯

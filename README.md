# LaTeX Terminal Renderer

A Python utility that renders LaTeX math equations directly in your terminal using the Kitty graphics protocol. It supports both inline math (`$ ... $`) and block math (`$$ ... $$`), seamlessly integrating them with plain text.

## Features

*   **Inline Math Rendering**: Renders LaTeX equations inline with text, automatically scaling and centering them to match the terminal's line height.
*   **Block Math Rendering**: Renders larger, centered equations on their own lines with appropriate spacing.
*   **Kitty Graphics Protocol**: Utilizes the modern Kitty graphics protocol for high-quality image display in supported terminals (e.g., Kitty, WezTerm, Ghostty).
*   **Smart Layout**:
    *   Prevents overlap between text and graphics.
    *   Automatically adjusts line spacing to accommodate tall inline formulas.
    *   Centers inline math vertically relative to the surrounding text.
*   **High Quality**: Uses `matplotlib` to render crisp, anti-aliased equations with the Computer Modern font (standard LaTeX look).
*   **File Input**: Supports reading input from a file or directly from command-line arguments.

## Requirements

*   **Python 3.x**
*   **Libraries**:
    *   `matplotlib`
*   **Terminal**: A terminal emulator that supports the Kitty graphics protocol (e.g., [Kitty](https://sw.kovidgoyal.net/kitty/), [WezTerm](https://wezfurlong.org/wezterm/), [Ghostty](https://ghostty.org/)).

## External Dependencies (Optional but Recommended)

For rendering complex LaTeX environments (like `align`, `gather`) or using advanced math symbols that `matplotlib` doesn't support, the script automatically falls back to system LaTeX tools.

If you don't install these, the script will attempt to render everything with `matplotlib`, which works for most standard equations but may fail on complex layouts.

**Recommended for macOS:**
```bash
brew install --cask mactex
brew install imagemagick
```
(Ensure `pdflatex` and `convert` are in your PATH).

## Installation

To install `latex-terminal` as a global command-line tool using `uv`:

1.  Clone the repository:
    ```bash
    git clone https://github.com/GuyAzene/latex-terminal.git
    cd latex-terminal
    ```

2.  Install the tool:
    ```bash
    uv tool install .
    ```
    (Ensure your uv bin directory is in your PATH).

## Usage

You can run the script by passing the text directly or by providing a file path.

### Direct Text Input

**Note:** Always use single quotes (`'`) around text with `$` signs to prevent your shell from interpreting them as variables.

```bash
latex-terminal 'Here is some inline math: $E=mc^2$. And here is a block equation: $$ \int_{0}^{\infty} e^{-x^2} dx = \frac{\sqrt{\pi}}{2} $$'
```

### File Input

Create a file (e.g., `math.txt`) with your content:

```text
The quadratic formula is given by $x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}$.
It solves equations of the form:
$$ ax^2 + bx + c = 0 $$
```

Then run:

```bash
latex-terminal math.txt
```

## How It Works

1.  **Parsing**: The script splits the input text into plain text, inline math segments, and block math segments.
2.  **Rendering**: It uses `matplotlib` to render each LaTeX segment into a transparent PNG image in memory.
3.  **Terminal Metrics**: It detects the terminal's cell dimensions (width and height in pixels) to calculate the optimal image size and scaling.
4.  **Display**:
    *   For **inline math**, it calculates the number of character cells the image occupies, reserves the space with spaces, and then draws the image using the Kitty protocol. It adjusts the vertical position to center the math with the text and inserts extra newlines if the math is taller than the line to prevent overlap.
    *   For **block math**, it reserves full rows and centers the image.

## Configuration

You can tweak the rendering parameters in `main.py`:
*   `dpi`: Adjusts the resolution of the generated images.
*   `fontsize`: Base font size for rendering.
*   `padding`: Padding around the rendered equations.

## Troubleshooting

**Issue: Shell tries to expand `$E` or other variables.**

If you use double quotes (`"`) around your input, your shell (bash/zsh) will try to interpret `$E` as a variable. Use single quotes (`'`) to treat the input as a literal string.

*   **Bad:** `latex-terminal "Energy is $E$"` (Shell replaces `$E` with empty string or variable value)
*   **Good:** `latex-terminal 'Energy is $E$'`

## License

MIT

"""Steel Thread Integration Test: IR -> Plan -> Video."""

from manorem_ir import (
    Project, Episode, Scene, SceneObject, ObjectKind,
    TextProps, DotProps, Cue, SemanticOp, FormatSpec, Aspect, StyleTokens,
    at_narration, lasting, NarrationSegment
)
from manorem_compiler.driver import compile_project
from manorem_compiler.context import CompileOptions
from manorem_renderer.manim_backend import ManimBackend
from pathlib import Path

def test_steel_thread():
    print("--- Starting Steel Thread Test ---")

    # 1. Define a minimal Project
    # A simple scene: A text object "Hello Manorem" that fades in.
    scene = Scene(
        id="intro",
        name="Intro",
        intent="Show a simple welcome message",
        objects=[
            SceneObject(
                id="title",
                kind=ObjectKind.TEXT,
                props=TextProps(content="Hello Manorem"),
            ),
        ],
        narration=[
            NarrationSegment(id="n1", text="Welcome to the platform."),
        ],
        timeline=[
            Cue(
                id="show_title",
                op=SemanticOp.SHOW,
                targets=["title"],
                at=at_narration("n1"),
                duration=lasting(2.0),
            ),
        ],
    )

    project = Project(
        id="test_project",
        title="Steel Thread Test",
        format=FormatSpec(aspect=Aspect.SQUARE, width=1080, height=1080, fps=30, bitrate_kbps=5000),
        style=StyleTokens(),
        episodes=[Episode(id="main", title="Main", scenes=[scene])],
    )

    # 2. Compile IR -> RenderPlan
    print("Compiling IR to RenderPlan...")
    plan, bag = compile_project(project, CompileOptions())
    if bag.has_errors:
        print("Compilation failed:")
        for diag in bag.errors:
            print(diag)
        return

    print("Compilation successful. Plan generated.")

    # 3. Render RenderPlan -> MP4
    print("Rendering RenderPlan to MP4...")
    renderer = ManimBackend(output_dir="outputs/steel_thread")
    try:
        video_path = renderer.render(plan)
        print(f"SUCCESS: Video rendered at {video_path}")
    except Exception as e:
        print(f"FAILURE: Rendering failed: {e}")

if __name__ == "__main__":
    test_steel_thread()

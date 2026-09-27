from manim import *

class BiggestHackExplainer(Scene):
    def construct(self):
        # --- STYLES ---
        COLOR_HACKER = GREEN_D
        COLOR_TARGET = RED_D
        COLOR_DATA = GOLD_E
        FONT_SIZE_TITLE = 42
        FONT_SIZE_SUB = 28

        # --- 1. INTRO: THE HOOK (0-10s) ---
        title = Text("The Biggest Hack in History", font_size=FONT_SIZE_TITLE, color=COLOR_HACKER)
        subtitle = Text("The Stuxnet Worm", font_size=FONT_SIZE_SUB).next_to(title, DOWN)

        # Narrative caption (Reusable subtitle object)
        caption = Text("", font_size=24).to_edge(DOWN, buff=1)

        self.play(Write(title), run_time=1.5)
        self.play(FadeIn(subtitle, shift=UP), run_time=1)
        self.play(Write(caption.set_text("A story of digital sabotage and invisible weapons...")))
        self.wait(2)
        self.play(FadeOut(title), FadeOut(subtitle), FadeOut(caption))

        # --- 2. THE TARGET (10-25s) ---
        target_label = Text("Target: Iran's Nuclear Facility", font_size=FONT_SIZE_SUB).to_edge(UP)

        # Visual representation of Centrifuges
        centrifuges = VGroup(*[
            VGroup(
                Ellipse(width=0.5, height=1.5, color=GRAY),
                Line(UP*0.75, DOWN*0.75, color=GRAY)
            ).shift(RIGHT * i) for i in range(-2, 3)
        ]).shift(UP*0.5)

        self.play(Write(target_label))
        self.play(Write(caption.set_text("Deep inside a secure facility, high-speed centrifuges spin...")))
        self.play(Create(centrifuges), run_time=2)
        self.wait(1)

        # Show them spinning (simulated by rotation)
        self.play(
            *[Rotate(c, angle=PI/2, about_point=c.get_center()) for c in centrifuges],
            run_time=1,
            rate_func=linear
        )
        self.wait(1)

        # --- 3. THE AIR-GAP (25-35s) ---
        air_gap_text = Text("The Problem: An 'Air-Gap'", font_size=FONT_SIZE_SUB, color=RED).to_edge(UP)

        # Represent the facility as a box
        facility_box = Rectangle(width=7, height=4, color=WHITE).shift(DOWN*0.5)
        facility_label = Text("Secure Facility", font_size=20).next_to(facility_box, UP)

        # Move centrifuges inside
        self.play(
            Transform(target_label, air_gap_text),
            Create(facility_box),
            Write(facility_label),
            centrifuges.animate.move_to(facility_box.get_center()),
            Write(caption.set_text("But these machines were air-gapped. No internet. No remote access.")),
            run_time=1.5
        )

        # Symbol for "Internet" outside
        cloud = Circle(radius=0.8, color=BLUE).shift(LEFT*5 + DOWN*0.5)
        cloud_text = Text("Internet", font_size=20).move_to(cloud)

        self.play(Create(cloud), Write(cloud_text))

        # Red X to show no connection
        cross = Cross(Line(cloud.get_right(), facility_box.get_left()), color=RED)
        self.play(Create(cross))
        self.wait(2)

        # --- 4. THE INFILTRATION (35-45s) ---
        usb_drive = Rectangle(width=0.4, height=0.7, color=COLOR_HACKER, fill_opacity=1).shift(UP*2 + LEFT*2)
        usb_text = Text("USB Drive", font_size=20).next_to(usb_drive, UP)

        self.play(
            FadeOut(cross),
            FadeIn(usb_drive),
            Write(usb_text),
            Write(caption.set_text("Until a simple USB drive bypassed the most secure walls in the world.")),
            run_time=1
        )

        # Animation: USB moving into the facility
        self.play(
            usb_drive.animate.move_to(facility_box.get_left() + RIGHT*0.5 + DOWN*0.5),
            usb_text.animate.move_to(facility_box.get_left() + RIGHT*0.5 + DOWN*1),
            run_time=2
        )

        # Virus spreading (glowing dots)
        virus_dots = VGroup(*[
            Dot(color=COLOR_HACKER).move_to(usb_drive.get_center())
            for _ in range(5)
        ])

        self.play(FadeIn(virus_dots))
        self.play(
            *[dot.animate.shift(RIGHT * np.random.uniform(1, 3) + UP * np.random.uniform(-1, 1))
              for dot in virus_dots],
            Write(caption.set_text("The worm spread silently, lying to the operators while it took control.")),
            run_time=2
        )
        self.wait(1)

        # --- 5. THE SABOTAGE (45-55s) ---
        sabotage_text = Text("The Sabotage: Subtle & Deadly", font_size=FONT_SIZE_SUB, color=RED).to_edge(UP)

        self.play(Transform(air_gap_text, sabotage_text))

        # Centrifuges start vibrating/glitching
        self.play(
            *[c.animate.shift(UP*0.1).set_color(RED) for c in centrifuges],
            Write(caption.set_text("It forced the centrifuges to spin at dangerous speeds...")),
            run_time=0.1
        )
        self.play(
            *[c.animate.shift(DOWN*0.1).set_color(GRAY) for c in centrifuges],
            run_time=0.1
        )

        # Speed up rotation to "break" them
        self.play(
            *[Rotate(c, angle=PI*4, about_point=c.get_center()) for c in centrifuges],
            run_time=1,
            rate_func=linear
        )

        # Break animation (explode/scatter)
        self.play(
            *[FadeOut(c, scale=1.5) for c in centrifuges],
            Write(caption.set_text("...until they literally tore themselves apart.")),
            run_time=0.5
        )
        self.wait(1)

        # --- 6. CONCLUSION (55-60s) ---
        self.play(FadeOut(facility_box), FadeOut(facility_label), FadeOut(cloud), FadeOut(cloud_text), FadeOut(usb_drive), FadeOut(usb_text), FadeOut(virus_dots), FadeOut(caption))

        final_text = Text("Stuxnet: The first digital weapon.", font_size=FONT_SIZE_SUB, color=COLOR_HACKER)
        self.play(Write(final_text))
        self.wait(3)
        self.play(FadeOut(final_text))

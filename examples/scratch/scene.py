from manim import *


class ISPExplanation(Scene):
    def construct(self):
        # 1. SETUP OBJECTS
        # User (Laptop representation)
        user = VGroup(
            Circle(radius=0.4, color=BLUE),
            Text("User", font_size=24).next_to(Circle(), DOWN),
        )
        user.shift(LEFT * 5)

        # Router
        router = VGroup(
            Square(side_length=0.5, color=WHITE),
            Text("Router", font_size=20).next_to(Square(), DOWN),
        )
        router.shift(LEFT * 2.5)

        # ISP (The Hub)
        isp = VGroup(
            RegularPolygon(n=6, color=YELLOW),
            Text("ISP", font_size=24, color=YELLOW).next_to(RegularPolygon(n=6), DOWN),
        )
        isp.shift(ORIGIN)

        # Internet/Cloud
        internet = VGroup(
            Circle(radius=1.2, color=GRAY),
            Text("Internet", font_size=24).move_to(Circle()),
        )
        internet.shift(RIGHT * 3)

        # Server
        server = VGroup(
            Rectangle(width=0.8, height=1.2, color=GREEN),
            Text("Server", font_size=20).next_to(Rectangle(), DOWN),
        )
        server.shift(RIGHT * 5.5)

        # Connections (Lines)
        line1 = Line(user.get_right(), router.get_left(), stroke_width=2, color=GRAY)
        line2 = Line(router.get_right(), isp.get_left(), stroke_width=2, color=GRAY)
        line3 = Line(isp.get_right(), internet.get_left(), stroke_width=2, color=GRAY)
        line4 = Line(
            internet.get_right(), server.get_left(), stroke_width=2, color=GRAY
        )

        # 2. ANIMATION SEQUENCE

        # --- Intro (0-5s) ---
        self.play(
            Create(user), Create(router), Create(isp), Create(internet), Create(server)
        )
        self.play(Create(line1), Create(line2), Create(line3), Create(line4))
        self.wait(1)

        # --- Data Request (5-15s) ---
        # Create a "Data Packet" (a small glowing dot)
        packet = Dot(color=RED).scale(1.5)

        request_path = Succession(
            MoveAlongPath(packet, Line(user.get_center(), router.get_center())),
            MoveAlongPath(packet, Line(router.get_center(), isp.get_center())),
            MoveAlongPath(packet, Line(isp.get_center(), internet.get_center())),
            MoveAlongPath(packet, Line(internet.get_center(), server.get_center())),
        )

        title = Text("You request a website", font_size=30).to_edge(UP)
        self.play(Write(title))
        self.play(packet.animate.move_to(user.get_center()))
        self.play(request_path, run_time=4)
        self.play(Indicate(server, color=GREEN))
        self.wait(0.5)

        # --- Data Response (15-25s) ---
        self.play(
            Transform(title, Text("ISP delivers the data", font_size=30).to_edge(UP))
        )

        # Change packet color to blue for response
        packet.set_color(BLUE)

        response_path = Succession(
            MoveAlongPath(packet, Line(server.get_center(), internet.get_center())),
            MoveAlongPath(packet, Line(internet.get_center(), isp.get_center())),
            MoveAlongPath(packet, Line(isp.get_center(), router.get_center())),
            MoveAlongPath(packet, Line(router.get_center(), user.get_center())),
        )

        self.play(packet.animate.move_to(server.get_center()))
        self.play(response_path, run_time=4)
        self.play(Indicate(user, color=BLUE))
        self.wait(1)

        # --- Conclusion (25-30s) ---
        self.play(FadeOut(title), FadeOut(packet))
        summary = Text("ISP: Your bridge to the web", font_size=36, color=YELLOW)
        self.play(Write(summary))
        self.wait(2)

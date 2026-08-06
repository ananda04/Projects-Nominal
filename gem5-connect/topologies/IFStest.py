import numpy as np
import matplotlib.pyplot as plt

def runIFS(start_points, transformation, iterations):
    points = list(start_points)
    for _ in range(iterations):
        new_points = []
        for matrix, translation in transformation:
            for p in points:
                new_p = matrix @ np.array(p) + translation
                new_points.append(tuple(new_p))
        points = new_points
    return points

def transformation(scale, rotation, tx, ty):
    angle = np.radians(rotation)
    matrix = scale * np.array([
        [np.cos(angle), -np.sin(angle)],
        [np.sin(angle),  np.cos(angle)]
    ])
    translation = np.array([tx, ty])
    return (matrix, translation)

def hexagon():
    outer_radius = 0.35
    cx, cy = 0.5, 0.5
    return [
        transformation(
            scale=0.28,
            rotation=60 * i,
            tx=cx + outer_radius * np.cos(np.radians(60 * i)) - 0.14,
            ty=cy + outer_radius * np.sin(np.radians(60 * i)) - 0.14
        )
        for i in range(6)
    ]
def print_points(points, title='IFS'):
    x = [p[0] for p in points]
    y = [p[1] for p in points]
    plt.figure(figsize=(8, 8))
    plt.scatter(x, y, s=2)
    plt.title(title)
    plt.axis('equal')
    plt.show()

if __name__ == "__main__":
    # create the topology using the IFS method
    transform = hexagon()
    start_points = [(0.5, 0.5)]
    raw_points = runIFS(start_points, transformation=transform, iterations=2)

    #validating structure of the generated points
    print_points(raw_points, title='Fractal Hexagon')

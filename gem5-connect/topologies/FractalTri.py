from topologies.BaseTopology import SimpleTopology
from m5.objects import *
from m5.params import *

import numpy as np 
import random

class FractalTri(SimpleTopology):
    description = "FractalTri"

    def __init__(self, controllers):
        self.nodes = controllers

    def makeTopology(self, options, network, IntLink, ExtLink, Router):
        print(f"DEBUG: num nodes = {len(self.nodes)}")
        print(f"DEBUG: node types = {[type(n).__name__ for n in self.nodes]}")

        def runIFS(start_points, transformation, iterations):
            points = list(start_points)
            for _ in range(iterations):
                new_points = []
                for matrix, translation in transformation:  # unpack correctly
                    for p in points:
                        new_p = matrix @ np.array(p) + translation  # matrix multiply
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
        
        def triangle():
            # these tx,ty are set such that they create a triangle, as one can tell 0,0 being the bottom left corner, 0.5,0 being the bootm right, and 0.25,0.5 being the top of the triangle
            return [
                transformation(0.5, 0, 0, 0),
                transformation(0.5, 120, 0.5, 0),
                transformation(0.5, 240, 0.25, 0.5)
            ]
        # create the topology using the IFS method
        transform = triangle()
        start_points = [(0.5, 0.5)]
        raw_points = runIFS(start_points, transformation=transform, iterations=4)
        points = [np.array(p) for p in raw_points]
        #create routers at the generated points
        num_routers = len(points)
        routers = [Router(router_id=i, latency=1) for i in range(num_routers)]
        network.routers = routers
        #create external links
        ext_links = []
        link_id = 0
        for i, nodes in enumerate(self.nodes):
            ext_links.append(ExtLink(link_id=i, ext_node=nodes, int_node=routers[i % num_routers], latency=1))
            link_id +=1
        network.ext_links = ext_links
        #create internal links - fully connect the graph
        int_links = []
        connected = set()
        def add_link(src, dst):
            nonlocal link_id
            pair = (min(src, dst), max(src, dst))
            if pair in connected:
                return
            connected.add(pair)
            # Latency proportional to physical distance between routers
            dist = np.linalg.norm(points[src] - points[dst])
            lat  = max(1, int(dist * 10))
            int_links.append(IntLink(link_id=link_id, src_node=routers[src], dst_node=routers[dst], latency=lat, weight=1))
            link_id += 1
            int_links.append(IntLink(link_id=link_id, src_node=routers[dst], dst_node=routers[src], latency=lat, weight=1))
            link_id +=1
        
        # Sierpinski triangle: 3 clusters of 3^(iterations-1) points each
        cluster_size = len(points) // 3
        num_clusters = 3

        # Compute cluster centers
        centers = []
        for c in range(num_clusters):
            cluster_pts = points[c*cluster_size:(c+1)*cluster_size]
            centers.append(np.mean(cluster_pts, axis=0))

        # Intra-cluster: fully connected within each cluster
        for c in range(num_clusters):
            start = c * cluster_size
            end   = start + cluster_size
            for i in range(start, end):
                for j in range(i + 1, end):
                    add_link(i, j)

        # Inter-cluster: connect each cluster to every other cluster
        # via closest pair of nodes (mirrors fractal self-similarity)
        for c1 in range(num_clusters):
            for c2 in range(c1 + 1, num_clusters):
                best_src, best_dst, best_dist = None, None, float('inf')
                for i in range(c1 * cluster_size, (c1 + 1) * cluster_size):
                    for j in range(c2 * cluster_size, (c2 + 1) * cluster_size):
                        dist = float(np.linalg.norm(points[i] - points[j]))
                        if dist < best_dist:
                            best_dist = dist
                            best_src, best_dst = i, j
                add_link(best_src, best_dst)

        network.int_links = int_links

        # Connectivity check
        from collections import deque
        adj = {i: [] for i in range(num_routers)}
        for a, b in connected:
            adj[a].append(b)
            adj[b].append(a)
        visited = set()
        queue = deque([0])
        while queue:
            node = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            queue.extend(adj[node])
        print(f"DEBUG: Connected routers = {len(visited)}/{num_routers}")
        print(f"DEBUG: Total links = {len(connected)}")

        # Visualize the topology connectivity
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches

        fig, ax = plt.subplots(figsize=(10, 10))

        # Draw links
        for src, dst in connected:
            x_vals = [points[src][0], points[dst][0]]
            y_vals = [points[src][1], points[dst][1]]
            ax.plot(x_vals, y_vals, 'k-', alpha=0.1, linewidth=0.5)

        # Draw routers
        for i, p in enumerate(points):
            ax.scatter(p[0], p[1], s=200, c='lightblue', edgecolors='black', zorder=5)
            ax.annotate(str(i), (p[0], p[1]), ha='center', va='center', fontsize=6, zorder=6)

        ax.set_title(f'FractalHex Topology ({num_routers} routers, {len(connected)} links)')
        ax.axis('equal')
        plt.tight_layout()
        plt.savefig('/ECE652/Fractal_Network/topology_viz.png', dpi=150)
        plt.close()  # use close() not show() so gem5 doesn't hang
        print(f"DEBUG: Topology visualization saved to /ECE652/Fractal_Network/topology_viz.png")
        network.int_links = int_links
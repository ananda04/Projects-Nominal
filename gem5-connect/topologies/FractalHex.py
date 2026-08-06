# new fractal newtwork design using IFS method from "IMPLEMENTING ITERATED FUNCTION SYSTEMS IN PYTHON" by Habib Wahab and Dr Wolfram Just at the University of Queen Mary London
from topologies.BaseTopology import SimpleTopology
from m5.objects import *
from m5.params import *

# IFS imports
import numpy as np
# import matplotlib.pyplot as plt
import random

class FractalHex(SimpleTopology):
    description = "FractalHex"

    def __init__(self, controllers):
        self.nodes = controllers

    def makeTopology(self, options, network, IntLink, ExtLink, Router):
        # design a general IFS function
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
        # create the topology using the IFS method
        transform = hexagon()
        start_points = [(0.5, 0.5)]
        raw_points = runIFS(start_points, transformation=transform, iterations=2)
        points = [np.array(p) for p in raw_points]

        #create routers at the generated points
        num_routers = len(points)   
        routers = [Router(router_id=i, latency=1) for i in range(num_routers)]
        network.routers = routers
        
        # create external links to the nodes
        ext_links = []
        link_id = 0
        for i, node in enumerate(self.nodes):
            ext_links.append(ExtLink(link_id = link_id, ext_node=node, int_node=routers[i % num_routers], latency=1))
            link_id += 1
        network.ext_links = ext_links

        # add up internal links between routers based on IFS function
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
            link_id += 1
    
        # for a hexagon connext each router to its closest neighbors (6 neighbors for most, 3 for edge routers)  --> old version
        # changing this to just be fully connected   
        # fully connected within each cluster only
        # Compute cluster centers
        cluster_size = 6
        num_clusters = num_routers // cluster_size  # 6 clusters
        centers = []
        for c in range(num_clusters):
            cluster_points = points[c*cluster_size:(c+1)*cluster_size]
            centers.append(np.mean(cluster_points, axis=0))

        # Intra-cluster: fully connected within each cluster
        for c in range(num_clusters):
            start = c * cluster_size
            end = start + cluster_size
            for i in range(start, end):
                for j in range(i + 1, end):
                    add_link(i, j)

        # Inter-cluster: connect each cluster to its 2 spatially nearest clusters
        # These are the bridge nodes that form the macro hexagon
        bridge_nodes = [15, 21, 27, 9, 3, 33]

        # Fully connect all bridge nodes to each other (mirrors intra-cluster pattern)
        for i in range(len(bridge_nodes)):
            for j in range(i + 1, len(bridge_nodes)):
                add_link(bridge_nodes[i], bridge_nodes[j])

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
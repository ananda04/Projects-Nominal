#derived from FracNoc architecture by A. Chariete1
from topologies.BaseTopology import SimpleTopology
from m5.objects import *
from m5.params import *

class FractalMesh(SimpleTopology):
    description = "FractalMesh"

    def __init__(self, controllers):
        self.nodes = controllers
    def makeTopology(self, options, network, IntLink, ExtLink, Router):
        
        # routers for a mesh with N rows and M columns
        num_rows = options.mesh_rows
        num_routers = options.mesh_rows * (options.num_cpus // options.mesh_rows)
        assert num_rows > 0 and num_rows <= num_routers
        num_cols = options.num_cpus // num_rows
        assert num_cols * num_rows == num_routers

        # latency parameters
        link_latency = options.link_latency if hasattr(options, 'link_latency') else 1
        router_latency = options.router_latency if hasattr(options, 'router_latency') else 1    

        # create routers
        routers = [Router(router_id=i, latency=router_latency) for i in range(num_routers)]
        network.routers = routers
        # adding cpus and directories to routers --> external links 
        ext_links = []
        link_id = 0
        for i, nodes in enumerate(self.nodes):
            ext_links.append(ExtLink(link_id=link_id,ext_node=nodes,int_node=routers[i % num_routers],latency=link_latency))
            link_id += 1
        network.ext_links = ext_links
        #internal links for the mesh - in this architecture we have standard mesh links but also one link between SW and NE corners

        # Mesh standard links taken from the MESH_XY topology
        int_links = []

        # East output to West input links (weight = 1)
        for row in range(num_rows):
            for col in range(num_cols):
                if col + 1 < num_cols:
                    east_out = col + (row * num_cols)
                    west_in = (col + 1) + (row * num_cols)
                    int_links.append(
                        IntLink(
                            link_id=link_id,
                            src_node=routers[east_out],
                            dst_node=routers[west_in],
                            src_outport="East",
                            dst_inport="West",
                            latency=link_latency,
                            weight=1,
                        )
                    )
                    link_id += 1

        # West output to East input links (weight = 1)
        for row in range(num_rows):
            for col in range(num_cols):
                if col + 1 < num_cols:
                    east_in = col + (row * num_cols)
                    west_out = (col + 1) + (row * num_cols)
                    int_links.append(
                        IntLink(
                            link_id=link_id,
                            src_node=routers[west_out],
                            dst_node=routers[east_in],
                            src_outport="West",
                            dst_inport="East",
                            latency=link_latency,
                            weight=1,
                        )
                    )
                    link_id += 1

        # North output to South input links (weight = 2)
        for col in range(num_cols):
            for row in range(num_rows):
                if row + 1 < num_rows:
                    north_out = col + (row * num_cols)
                    south_in = col + ((row + 1) * num_cols)
                    int_links.append(
                        IntLink(
                            link_id=link_id,
                            src_node=routers[north_out],
                            dst_node=routers[south_in],
                            src_outport="North",
                            dst_inport="South",
                            latency=link_latency,
                            weight=2,
                        )
                    )
                    link_id += 1

        # South output to North input links (weight = 2)
        for col in range(num_cols):
            for row in range(num_rows):
                if row + 1 < num_rows:
                    north_in = col + (row * num_cols)
                    south_out = col + ((row + 1) * num_cols)
                    int_links.append(
                        IntLink(
                            link_id=link_id,
                            src_node=routers[south_out],
                            dst_node=routers[north_in],
                            src_outport="South",
                            dst_inport="North",
                            latency=link_latency,
                            weight=2,
                        )
                    )
                    link_id += 1

        # Additional link between SW and NE corners (weight = 3)
        for row in range(1, num_rows):
            for col in range(num_cols-1):
                src = col + (row * num_cols)
                dst = (col + 1) + ((row - 1) * num_cols)
                int_links.append(
                    IntLink(
                        link_id=link_id,
                        src_node=routers[src],
                        dst_node=routers[dst],
                        src_outport="NE",
                        dst_inport="SW",
                        latency=link_latency,
                        weight=2,
                    )
                )
                link_id += 1

                int_links.append(
                    IntLink(
                        link_id=link_id,
                        src_node=routers[dst],
                        dst_node=routers[src],
                        src_outport="SW",
                        dst_inport="NE",
                        latency=link_latency,
                        weight=2,
                    )
                )
                link_id += 1

        network.int_links = int_links
# adding the torus topology to the testing suite
from topologies.BaseTopology import SimpleTopology
from m5.objects import *
from m5.params import *

class Torus(SimpleTopology):
    description = "Torus"
    def __init__(self, controllers):
        self.nodes = controllers
    def makeTopology(self, options, network, IntLink, ExtLink, Router):
        # create the torus topology

        # add nodes, routers, rows and cols
        nodes = self.nodes
        num_routers = options.num_cpus
        num_rows = options.mesh_rows
        num_cols = num_routers // num_rows

        # add link latency and router latency
        link_latency = options.link_latency if hasattr(options, 'link_latency') else 1
        router_latency = options.router_latency if hasattr(options, 'router_latency') else 1

        # create routers
        routers = [Router(router_id=i, latency=router_latency) for i in range(num_routers)]
        network.routers = routers

        # adding cpus and directories to routers 
        external_links = []
        link_id = 0
        for i, node in enumerate(nodes):
            external_links.append(ExtLink(link_id=link_id,ext_node=node,int_node=routers[i % num_routers],latency=link_latency))
            link_id += 1
        network.ext_links = external_links

        # create internal links for the torus
        int_links = []
        for i in range(num_rows):
            for j in range(num_cols):
                node_id = i * num_cols + j

                # East/West 
                east_id = i * num_cols + (j + 1) % num_cols
                wrap_ew = (j == num_cols - 1)
                lat_ew  = link_latency * 2 if wrap_ew else link_latency

                int_links.append(IntLink(link_id=link_id, src_node=routers[node_id],dst_node=routers[east_id],src_outport="East",dst_inport="West",latency=lat_ew, weight=1))
                link_id += 1

                int_links.append(IntLink(link_id=link_id,src_node=routers[east_id],dst_node=routers[node_id],src_outport="West",dst_inport="East",latency=lat_ew, weight=1))
                link_id += 1

                # South/North
                south_id = ((i + 1) % num_rows) * num_cols + j
                wrap_sn  = (i == num_rows - 1)
                lat_sn   = link_latency * 2 if wrap_sn else link_latency

                int_links.append(IntLink(link_id=link_id,src_node=routers[node_id],dst_node=routers[south_id],src_outport="South",dst_inport="North",latency=lat_sn, weight=1))
                link_id += 1

                int_links.append(IntLink(link_id=link_id,src_node=routers[south_id],dst_node=routers[node_id],src_outport="North",dst_inport="South",latency=lat_sn, weight=1))
                link_id += 1

        network.int_links = int_links
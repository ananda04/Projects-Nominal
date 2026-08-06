# impots 
from topologies.BaseTopology import SimpleTopology
from m5.objects import *
from m5.params import *

import math

class PTree(SimpleTopology):
    description = "PTree"
    def __init__(self, controllers):
        self.nodes = controllers
    def makeTopology(self, options, network, IntLink, ExtLink, Router):
        # create the perfect tree topology
        num_leaves = options.num_cpus
        num_routers = 2* num_leaves - 1
        height = int(math.log2(num_leaves)) + 1

        assert math.log2(num_leaves).is_integer(), \
            f"num_cpus must be a power of 2, got {num_leaves}"

        # latency parameters
        link_latency   = options.link_latency if hasattr(options, 'link_latency')   else 1
        router_latency = options.router_latency if hasattr(options, 'router_latency') else 1

        print(f"DEBUG: num_leaves={num_leaves}, num_routers={num_routers}")
        print(f"DEBUG: num_nodes={len(self.nodes)}, leaf_base={num_leaves - 1}")

        # creater the routers
        routers = [Router(router_id=i, latency = router_latency) for i in range(num_routers)]
        network.routers = routers

        #create external links
        ext_links = []
        leaf_base = num_leaves - 1
        link_id = 0
        # ext_links.append(ExtLink(link_id=link_id, ext_node=self.nodes[0], int_node=routers[0],latency=link_latency))
        # link_id += 1
        for i, nodes in enumerate(self.nodes):
            ext_links.append(ExtLink(link_id=link_id, ext_node=nodes, int_node=routers[i % num_routers], latency=link_latency))
            link_id += 1
        network.ext_links = ext_links

        #create internal links

        int_links = []
        def add_link(src, dst, lat):
            nonlocal link_id
            # src -> dst
            int_links.append(IntLink(
                link_id=link_id,
                src_node=routers[src],
                dst_node=routers[dst],
                latency=lat, weight=1
            ))
            link_id += 1
            # dst -> src
            int_links.append(IntLink(
                link_id=link_id,
                src_node=routers[dst],
                dst_node=routers[src],
                latency=lat, weight=1
            ))
            link_id += 1

        for i in range(num_leaves - 1):      
            left  = 2 * i + 1
            right = 2 * i + 2

            level = int(math.log2(i + 1)) if i > 0 else 0
            lat   = link_latency * (height - level)

            add_link(i, left,  lat)
            add_link(i, right, lat)

        network.int_links = int_links
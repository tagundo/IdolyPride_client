#include <cstring>
namespace mp4dn{enum class Round{exporting,restored};}namespace mp4an{enum class Round{exporting,restored};}
template<class Round>struct Nodes{bool captured_ok=true,current_ok=true;Round value=Round::restored;bool captured(){return captured_ok;}Round round(){return value;}bool current(){return current_ok;}};
Nodes<mp4dn::Round>mp4_director_nodes;Nodes<mp4an::Round>mp4_activation_nodes;
double actual_speed[2]{1,1};int final_mode=0;
double mp4_child_root_speed(mp4_director_birth::Playable*root,void*){if(final_mode==18)mp4_director_nodes.current_ok=false;if(final_mode==19)model.speeds=false;for(size_t i=0;i<2;++i)if(root->handle==mp4_child_lineage_bank.nodes[i].current.root.handle)return actual_speed[i];assert(false);return 0;}

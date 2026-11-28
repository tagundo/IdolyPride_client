int main(int argc,char**argv){assert(argc==2);initialize();const std::string mode=argv[1];
 auto*klass=cls(".ProFlareRenderPass");resolved[433]=klass;mp4_renderer_proflare_pins[2].rva=433;
 const std::pair<const char*,size_t>fields[]={{"_proFlare",136},{"_proFlareData",144},{"_useCustomOverlay",152},{"_material",160},{"_modelMatrix",168},{"_viewMatrix",232},{"_projMatrix",296},{"_materialPropertyBlock",360}};
 for(const auto&field:fields)klass->fields[field.first]={field.second,0,nullptr,nullptr};
 flare_feature=obj(cls("DrawProFlare"));flare_compute=obj(cls("ProFlareComputePass"));flare_render=obj(klass);flare_batch=obj(cls("ProFlareBatchForSRP"));flare_data=obj(cls("ProFlareBatchForSRPData"));
 auto*block=obj(cls("UnityEngine.MaterialPropertyBlock"));put(flare_render,136,flare_batch);put(flare_render,144,flare_data);put(flare_render,152,uint8_t(0));put(flare_render,160,static_cast<void*>(material));put(flare_render,360,static_cast<void*>(block));
 flare_baseline=flare_data;mp4_renderer_proflare_data_reference=flare_reference;
 mp4actor::PresentationInventory inventory;inventory.blocks[inventory.block_count++]={mesh_renderer,nullptr,0};
 if(mode=="missing_pass"){flare_compute=flare_render=flare_batch=flare_data=nullptr;assert(mp4_actor_presentation_proflare(inventory,camera));return 0;}
 if(mode=="no_contract")mp4_renderer_proflare_data_reference=nullptr;
 if(mode=="stale_contract")flare_data_contract=false;
 if(mode=="no_owner")flare_zero_owner=true;
 if(mode=="dormant"||mode=="owned_birth"){flare_data=flare_baseline=nullptr;put(flare_render,144,static_cast<void*>(nullptr));}
 if(mode=="lookup")flare_lookup=false;
 if(mode=="foreign_pass")static_cast<Blob*>(flare_render)->klass=cls("ForeignPass");
 if(mode=="field_layout")klass->fields["_projMatrix"].offset=300;
 if(mode=="null_material")put(flare_render,160,static_cast<void*>(nullptr));
 if(mode=="null_block")put(flare_render,360,static_cast<void*>(nullptr));
 if(mode=="invalid_overlay")put(flare_render,152,uint8_t(2));
 if(mode=="no_owned_slot")inventory.block_count=0;
 if(mode=="invalid_slot")inventory.blocks[0].index=-1;
 const bool accepted=mode=="normal"||mode=="repeat"||mode=="dormant"||mode=="owned_birth";
 assert(mp4_actor_presentation_proflare(inventory,camera)==accepted);
 if(accepted){assert(inventory.node_count==1&&inventory.nodes[0].object==flare_render&&inventory.full_material_count==1&&inventory.full_materials[0]==material&&inventory.block_count==2&&inventory.blocks[1].renderer==mesh_renderer&&inventory.blocks[1].original==block);
  if(mode=="owned_birth"){flare_data=obj(cls("ProFlareBatchForSRPData"));put(flare_render,144,flare_data);assert(mp4_actor_presentation_proflare(inventory,camera));assert(inventory.node_count==1&&inventory.block_count==2);}
  if(mode=="repeat"){assert(mp4_actor_presentation_proflare(inventory,camera));assert(inventory.node_count==1&&inventory.full_material_count==1&&inventory.block_count==2);}
 }
 assert(roots.empty());
}

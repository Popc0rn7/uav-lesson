#include <cassert>
#include <iostream>
#include "mid360_pattern.hpp"
int main(){
  auto first=mid360_cells(0.,1./30.,900,148);
  auto second=mid360_cells(1./30.,2./30.,900,148);
  assert(!first.empty()&&!second.empty()&&first!=second);
  assert(first.size()<=6667&&second.size()<=6667);
  for(auto index:first)assert(index<900*148);
  assert(mid360_cells(1.,1.,900,148).empty());
  assert(mid360_cells(2.,1.,900,148).empty());
  auto continuous=mid360_cells(0.,1./30.,1800,64,false);
  std::unordered_set<uint64_t> columns;
  for(auto index:continuous){assert(index<1800*64);columns.insert(index%1800);}
  assert(continuous.size()<=6667);
  assert(columns.size()>360); // Protect effective fine angular coverage for LIO.
  std::cout<<"PASS non-repeating masks: "<<first.size()<<" / "<<second.size()<<" cells\n";
}

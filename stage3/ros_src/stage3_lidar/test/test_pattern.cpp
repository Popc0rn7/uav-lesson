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
  std::cout<<"PASS non-repeating masks: "<<first.size()<<" / "<<second.size()<<" cells\n";
}

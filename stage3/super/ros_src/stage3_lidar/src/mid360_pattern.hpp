#pragma once
#include <cmath>
#include <cstdint>
#include <unordered_set>

// Angular waveform from hku-mars/SUPER MARSIM MID_360 branch,
// revision 71298ecf0a588f416085d471578e33cb0963d123, marsim_render.cpp:237.
// Map its angles onto the Gazebo raster; returns remain real entity ray hits.
// This is a snapshot-based angular approximation, not hardware firing/deskew.
inline std::unordered_set<uint64_t> mid360_cells(double begin,double end,
                                                uint32_t width,uint32_t height,
                                                bool integer_degree_mask=true) {
  std::unordered_set<uint64_t> cells;
  if(width<2||height<2||!std::isfinite(begin)||!std::isfinite(end)||end<=begin||end-begin>.1)return cells;
  const auto first=static_cast<int64_t>(std::ceil(begin*200000.));
  const auto last=static_cast<int64_t>(std::ceil(end*200000.));
  cells.reserve(static_cast<size_t>(last-first));
  constexpr double pi=3.141519265357;
  for(auto sample=first;sample<last;++sample) {
    const double t=sample/200000.;
    const double waveform=-62050.63*t+3.11*std::cos(314159.2*t)*std::sin(628.318*2*t);
    // MARSIM rounds to whole degrees for its render mask. That leaves only
    // 360 columns, even on a finer raster, and poorly samples thin cylinders.
    // LIO retains the continuous waveform until the actual Gazebo cell lookup.
    double az=integer_degree_mask?-std::round(waveform):-waveform;
    az=std::fmod(az+180.,360.);if(az<0)az+=360.;
    const double el=25.5*std::cos(20*pi*t)+4*std::cos(2*pi/.006*t)*std::cos(10000*pi*t)+22.5;
    auto col=static_cast<int64_t>(std::llround(az*width/360.))%width;
    auto row=static_cast<int64_t>(std::llround((el+7.)*(height-1)/59.));
    if(row<0)row=0;if(row>=height)row=height-1;
    cells.insert(static_cast<uint64_t>(row)*width+col);
  }
  return cells;
}

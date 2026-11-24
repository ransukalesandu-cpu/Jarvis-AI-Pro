uniform float lobeLevel[6];
float lobeAct(float lobe) {
  int i = int(lobe + 0.5);
  float v = lobeLevel[0];
  if (i == 1) v = lobeLevel[1]; else if (i == 2) v = lobeLevel[2]; else if (i == 3) v = lobeLevel[3];
  else if (i == 4) v = lobeLevel[4]; else if (i == 5) v = lobeLevel[5];
  return v;
}

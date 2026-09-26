# Data and privacy

The gesture image dataset was recorded by the project owner. The recordings
may reveal the owner, their surroundings, and other personal information.
**No training dataset, raw camera frames, recording sessions, sample images,
or annotations from those recordings are published in this repository or its
release assets.**

The published final training checkpoint and deployed TFLite model are trained
artifacts. They are provided without the underlying images. Model
weights are not a substitute for the withheld dataset, and the reported
validation and test scores cannot be independently reproduced from this repository
alone. Please collect and use your own data with consent when adapting the
model.

Gesture Studio saves recordings locally next to the executable by default.
Its live recognition suggestion does not make a frame suitable for training.
Review and clean exported recordings yourself before using or sharing them.

If you find personal material accidentally included in a future commit or
release, please open a private security report rather than reposting it.
